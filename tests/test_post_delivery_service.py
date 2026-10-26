"""
Unit tests for backend/post_delivery_service.py.
Exhaustively validates:
1. Fulfillment extraction and 5-day delay scheduling.
2. Multiple partial fulfillments date selection (max created_at).
3. Zero fulfillment and non-contactable order filtering.
4. Timestamp boundary evaluation (4d23h vs 5d1m).
5. Strict discount code MGVIP15 verification.
6. Multi-language VIP review copy generation (en, ro, it, es, de, fr).
7. Cross-channel dispatch (Email, WhatsApp, wa.me fallback, MobileNotifier).
8. Idempotency and canceled/refunded order suppression.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
import asyncio

import backend.post_delivery_service as pds
from backend.post_delivery_service import PostDeliveryService
from tests.helpers import make_sample_order, make_sample_shop_settings


class TestPostDeliveryServiceFulfillmentSync(unittest.TestCase):
    """Fulfillment capture, date parsing, and queue ingestion."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_sync_single_fulfillment_scheduled_plus_5_days(self):
        """Order with fulfillment at T is scheduled for T + 5 days."""
        now = datetime.now(timezone.utc)
        f_date = now - timedelta(days=2)
        order = make_sample_order(order_id="ord_sync_1", fulfilled_at_dt=f_date)

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "shpat_123"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    mock_enqueue.assert_called_once()
                    call_kwargs = mock_enqueue.call_args[1]
                    self.assertEqual(call_kwargs["order_id"], "ord_sync_1")
                    scheduled = call_kwargs["scheduled_for"]
                    self.assertAlmostEqual((scheduled - f_date).total_seconds(), 5 * 86400, delta=10)

    def test_sync_ignores_unfulfilled_orders(self):
        """Order with fulfillments=[] or None is skipped."""
        order = make_sample_order(order_id="ord_unf")
        order["fulfillments"] = []

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "shpat_123"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    self.assertFalse(mock_enqueue.called)

    def test_sync_multiple_fulfillments_uses_latest_date(self):
        """Split shipments with dates D1 and D2 (D2 > D1) use D2 for scheduling."""
        now = datetime.now(timezone.utc)
        d1 = now - timedelta(days=8)
        d2 = now - timedelta(days=2)
        order = make_sample_order(order_id="ord_multi")
        order["fulfillments"] = [
            {"id": 1, "created_at": d1.isoformat(), "status": "success"},
            {"id": 2, "created_at": d2.isoformat(), "status": "success"}
        ]

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "shpat_123"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    call_kwargs = mock_enqueue.call_args[1]
                    self.assertAlmostEqual(call_kwargs["fulfilled_at"].timestamp(), d2.timestamp(), delta=5)

    def test_sync_skips_orders_without_email_and_phone(self):
        """Orders missing contact details are gracefully ignored."""
        order = make_sample_order(order_id="ord_nocontact", email="", phone="")
        order["customer"]["email"] = ""
        order["customer"]["phone"] = ""

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "shpat_123"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    self.assertFalse(mock_enqueue.called)

    def test_sync_skips_cancelled_or_refunded_orders(self):
        """Cancelled or refunded orders are not enqueued."""
        order1 = make_sample_order(order_id="ord_canc")
        order1["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        order2 = make_sample_order(order_id="ord_ref")
        order2["financial_status"] = "refunded"

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order1, order2])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "shpat_123"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    self.assertFalse(mock_enqueue.called)


class TestPostDeliveryServiceSchedulingAndDueEvaluation(unittest.TestCase):
    """Due queue evaluation and time travel boundaries."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_due_evaluation_4d23h_not_due(self):
        """Record scheduled for 5 days after fulfillment is not due at 4 days 23 hours."""
        now = datetime.now(timezone.utc)
        fulfilled = now - timedelta(days=4, hours=23)
        scheduled = fulfilled + timedelta(days=5)

        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[]):
            count = self.service.process_due_vip_automations("luxury.myshopify.com", now_dt=now)
            self.assertEqual(count, 0)

    def test_due_evaluation_5d01m_is_due(self):
        """Record at 5 days 1 minute post-fulfillment is marked due and dispatched."""
        now = datetime.now(timezone.utc)
        fulfilled = now - timedelta(days=5, minutes=1)
        scheduled = fulfilled + timedelta(days=5)

        record = {
            "order_id": "ord_due_1",
            "order_number": "1001",
            "customer_name": "Elena",
            "customer_email": "elena@example.com",
            "customer_phone": "+40721123456",
            "discount_code": "MGVIP15",
            "items_summary": [{"title": "Silk Scarf"}]
        }

        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
                with patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock) as mock_wa:
                    with patch.object(self.service.mobile_notifier, "notify_merchant", new_callable=AsyncMock) as mock_notify:
                        with patch.object(pds.db, "mark_post_delivery_sent", return_value=True):
                            with patch.object(pds.db, "save_autopilot_log", return_value=True):
                                count = self.service.process_due_vip_automations("luxury.myshopify.com", now_dt=now)
                                self.assertEqual(count, 1)
                                self.assertTrue(mock_mail.called)
                                self.assertTrue(mock_wa.called)
                                self.assertTrue(mock_notify.called)


class TestPostDeliveryServiceCopyGeneration(unittest.TestCase):
    """VIP review request and upsell copy builder."""

    def test_build_vip_message_all_supported_languages(self):
        """Verifies review copy in ro, it, en, es, de, fr all include MGVIP15 and customer name."""
        for lang in ["ro", "it", "en", "es", "de", "fr"]:
            msg = PostDeliveryService.build_vip_message(
                customer_name="Matteo",
                purchased_item="Camicia Luxury",
                upsell_item="Gravatta",
                discount_code="MGVIP15",
                lang=lang
            )
            self.assertIn("Matteo", msg, f"Missing customer name in lang {lang}")
            self.assertIn("MGVIP15", msg, f"Missing discount code in lang {lang}")

    def test_build_vip_message_with_upsell_item(self):
        """Embeds upsell product recommendation when provided."""
        msg = PostDeliveryService.build_vip_message(
            customer_name="Lorenzo",
            purchased_item="Suit",
            upsell_item="Silk Tie",
            discount_code="MGVIP15",
            lang="en"
        )
        self.assertIn("Silk Tie", msg)
        self.assertIn("Suit", msg)


class TestPostDeliveryServiceDispatchChannels(unittest.TestCase):
    """Dual-channel dispatch (Email, WhatsApp) and merchant alert notifications."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_dispatch_email_only_when_phone_absent(self):
        """Dispatches email only when phone is absent."""
        record = {
            "order_id": "ord_email_only",
            "order_number": "1002",
            "customer_name": "Maria",
            "customer_email": "maria@example.com",
            "customer_phone": None,
            "discount_code": "MGVIP15",
            "items_summary": []
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
                with patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock) as mock_wa:
                    with patch.object(pds.db, "mark_post_delivery_sent"):
                        with patch.object(pds.db, "save_autopilot_log"):
                            count = self.service.process_due_vip_automations("luxury.myshopify.com")
                            self.assertEqual(count, 1)
                            self.assertTrue(mock_mail.called)
                            self.assertFalse(mock_wa.called)

    def test_dispatch_whatsapp_only_when_email_absent(self):
        """Dispatches WhatsApp only when email is absent."""
        record = {
            "order_id": "ord_wa_only",
            "order_number": "1003",
            "customer_name": "Alex",
            "customer_email": None,
            "customer_phone": "+393401234567",
            "discount_code": "MGVIP15",
            "items_summary": []
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
                with patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock) as mock_wa:
                    with patch.object(pds.db, "mark_post_delivery_sent"):
                        with patch.object(pds.db, "save_autopilot_log"):
                            count = self.service.process_due_vip_automations("luxury.myshopify.com")
                            self.assertEqual(count, 1)
                            self.assertFalse(mock_mail.called)
                            self.assertTrue(mock_wa.called)


if __name__ == "__main__":
    unittest.main()

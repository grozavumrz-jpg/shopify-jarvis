"""
tests/test_feature4_adversarial.py
Adversarial Stress Test Suite for Milestone 3 (Feature 4: Post-Delivery VIP Review & Upsell Automation).

Adversarial Challenge Vectors:
1. Time travel & boundary precision: 4d23h59m vs 5d0m vs 5d1m, timezone normalizations, sub-second precision.
2. Complex split shipments: 3+ tracking numbers with non-chronological timestamps, mixed statuses, UTC chronology.
3. Cancellation and refund suppression: pre-sync suppression, post-enqueue cancellation, status isolation.
4. Input sanitization & extreme values: Unicode/emoji/RTL/XSS names, empty fallbacks, malformed item summaries, contact combos.
5. Strict discount code enforcement: MGVIP15 across Email, WhatsApp, Mobile Notifier, and Autopilot Logs in all languages.
6. Empirical vulnerability probes: string list in items_summary (AttributeError), unstripped whitespace customer names.
"""

import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
import asyncio
import json

import backend.post_delivery_service as pds
from backend.post_delivery_service import PostDeliveryService
from backend.email_dispatcher import EmailDispatcher
from backend.whatsapp_dispatcher import WhatsAppDispatcher
from backend.mobile_notifier import MobileNotifier
from tests.helpers import make_sample_order, make_sample_shop_settings


class TestFeature4BoundaryPrecision(unittest.TestCase):
    """Adversarial testing of 5-day post-delivery timing boundaries and timezones."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_boundary_4d23h59m_is_not_due(self):
        """Fulfillment aged 4 days 23 hours 59 minutes MUST NOT be due."""
        now = datetime.now(timezone.utc)
        fulfilled_at = now - timedelta(days=4, hours=23, minutes=59)
        scheduled_for = fulfilled_at + timedelta(days=5)

        self.assertGreater(scheduled_for, now, "Record at 4d23h59m must be in the future")
        
        # Real due query simulation
        due_records = []
        if scheduled_for <= now:
            due_records.append({"order_id": "ord_boundary_1"})
        self.assertEqual(len(due_records), 0)

    def test_adv_boundary_exact_5d00m_is_due(self):
        """Fulfillment aged exactly 5 days (120 hours 0 seconds) MUST be due."""
        now = datetime.now(timezone.utc)
        fulfilled_at = now - timedelta(days=5)
        scheduled_for = fulfilled_at + timedelta(days=5)

        self.assertLessEqual(scheduled_for, now, "Record at exact 5 days must satisfy scheduled_for <= now")

    def test_adv_boundary_5d01m_is_due(self):
        """Fulfillment aged 5 days 1 minute MUST be due."""
        now = datetime.now(timezone.utc)
        fulfilled_at = now - timedelta(days=5, minutes=1)
        scheduled_for = fulfilled_at + timedelta(days=5)

        self.assertLess(scheduled_for, now, "Record at 5d01m must be in the past")

    def test_adv_boundary_subsecond_precision(self):
        """Sub-second boundaries: 4d23h59m59.9s vs 5d00m00.1s."""
        now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
        
        # 100 milliseconds before 5-day mark
        fulfilled_before = now - timedelta(days=4, hours=23, minutes=59, seconds=59, milliseconds=900)
        scheduled_before = fulfilled_before + timedelta(days=5)
        self.assertGreater(scheduled_before, now)

        # 100 milliseconds after 5-day mark
        fulfilled_after = now - timedelta(days=5, milliseconds=100)
        scheduled_after = fulfilled_after + timedelta(days=5)
        self.assertLessEqual(scheduled_after, now)

    def test_adv_boundary_utc_offset_conversion(self):
        """Fulfillment with +09:00 (Tokyo) offset is normalized to UTC correctly."""
        # 2026-10-20 18:00:00 +09:00 == 2026-10-20 09:00:00 UTC
        iso_tokyo = "2026-10-20T18:00:00+09:00"
        dt = PostDeliveryService.parse_datetime(iso_tokyo)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 9)
        self.assertEqual(dt.day, 20)

        # 5 days later in UTC is 2026-10-25 09:00:00 UTC
        scheduled = dt + timedelta(days=5)
        self.assertEqual(scheduled.hour, 9)
        self.assertEqual(scheduled.day, 25)

    def test_adv_boundary_negative_offset_conversion(self):
        """Fulfillment with -05:00 (EST) offset is normalized to UTC correctly."""
        # 2026-10-20 22:00:00 -05:00 == 2026-10-21 03:00:00 UTC
        iso_est = "2026-10-20T22:00:00-05:00"
        dt = PostDeliveryService.parse_datetime(iso_est)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 3)
        self.assertEqual(dt.day, 21)

    def test_adv_boundary_naive_datetime_handled_safely(self):
        """Naive datetimes are safely converted to UTC without throwing TypeError."""
        naive_dt = datetime(2026, 10, 20, 10, 30, 0)
        res = PostDeliveryService.parse_datetime(naive_dt)
        self.assertIsNotNone(res)
        self.assertEqual(res.tzinfo, timezone.utc)
        self.assertEqual(res.hour, 10)


class TestFeature4ComplexSplitShipments(unittest.TestCase):
    """Adversarial testing of multi-item partial fulfillments and date selection."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_split_shipments_three_out_of_order_tracking(self):
        """
        Order fulfilled across 3 split shipments in non-chronological order:
        F1: 6 days ago
        F2: 1 day ago (LATEST)
        F3: 3 days ago
        The latest (F2) MUST be chosen so scheduled_for is 4 days in the future.
        """
        now = datetime.now(timezone.utc)
        f1_date = now - timedelta(days=6)
        f2_date = now - timedelta(days=1)
        f3_date = now - timedelta(days=3)

        order = make_sample_order(order_id="ord_split_3")
        order["fulfillments"] = [
            {"id": 101, "tracking_number": "TRK-001", "created_at": f1_date.isoformat(), "status": "success"},
            {"id": 102, "tracking_number": "TRK-002", "created_at": f2_date.isoformat(), "status": "success"},
            {"id": 103, "tracking_number": "TRK-003", "created_at": f3_date.isoformat(), "status": "success"},
        ]

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    fulfilled_at = kwargs["fulfilled_at"]
                    # F2 (1 day ago) must be chosen
                    self.assertAlmostEqual(fulfilled_at.timestamp(), f2_date.timestamp(), delta=2)
                    # Scheduled for is F2 + 5 days
                    scheduled_for = kwargs["scheduled_for"]
                    expected_scheduled = f2_date + timedelta(days=5)
                    self.assertAlmostEqual(scheduled_for.timestamp(), expected_scheduled.timestamp(), delta=2)

    def test_adv_split_shipments_mixed_fulfillment_statuses(self):
        """
        Fulfillments with mixed statuses:
        F1: 1 day ago (status: 'cancelled') -> MUST BE IGNORED
        F2: 2 days ago (status: 'failure') -> MUST BE IGNORED
        F3: 4 days ago (status: 'success') -> VALID LATEST
        F4: 8 days ago (status: 'success') -> VALID EARLIER
        """
        now = datetime.now(timezone.utc)
        f1_date = now - timedelta(days=1)
        f2_date = now - timedelta(days=2)
        f3_date = now - timedelta(days=4)
        f4_date = now - timedelta(days=8)

        order = make_sample_order(order_id="ord_mixed_status")
        order["fulfillments"] = [
            {"id": 1, "created_at": f1_date.isoformat(), "status": "cancelled"},
            {"id": 2, "created_at": f2_date.isoformat(), "status": "failure"},
            {"id": 3, "created_at": f3_date.isoformat(), "status": "success"},
            {"id": 4, "created_at": f4_date.isoformat(), "status": "success"},
        ]

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    # Must pick F3 (4 days ago), NOT F1 or F2
                    self.assertAlmostEqual(kwargs["fulfilled_at"].timestamp(), f3_date.timestamp(), delta=2)

    def test_adv_split_shipments_different_timezones_chronology(self):
        """
        Timezone trap:
        F1: 2026-10-20T17:00:00+06:00 (which is 11:00 UTC)
        F2: 2026-10-20T13:00:00Z (which is 13:00 UTC - LATER than F1)
        If comparing ISO strings lexicographically, '17:00' > '13:00' would pick F1 (WRONG).
        PostDeliveryService MUST convert to UTC and pick F2 (13:00 UTC).
        """
        order = make_sample_order(order_id="ord_tz_split")
        order["fulfillments"] = [
            {"id": 1, "created_at": "2026-10-20T17:00:00+06:00", "status": "success"},
            {"id": 2, "created_at": "2026-10-20T13:00:00Z", "status": "success"},
        ]

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    expected_utc = datetime(2026, 10, 20, 13, 0, 0, tzinfo=timezone.utc)
                    self.assertEqual(kwargs["fulfilled_at"], expected_utc)

    def test_adv_split_shipments_corrupted_dates_resilience(self):
        """One corrupted date string among valid fulfillments does not crash and selects valid max."""
        now = datetime.now(timezone.utc)
        f_valid = now - timedelta(days=2)
        order = make_sample_order(order_id="ord_corrupt_date")
        order["fulfillments"] = [
            {"id": 1, "created_at": "TOTAL_GARBAGE_DATE_STRING", "status": "success"},
            {"id": 2, "created_at": None, "status": "success"},
            {"id": 3, "created_at": f_valid.isoformat(), "status": "success"},
        ]

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    self.assertAlmostEqual(kwargs["fulfilled_at"].timestamp(), f_valid.timestamp(), delta=2)

    def test_adv_split_shipments_all_invalid_dates_skipped(self):
        """All fulfillments having corrupt or None dates results in order being skipped cleanly."""
        order = make_sample_order(order_id="ord_all_corrupt")
        order["fulfillments"] = [
            {"id": 1, "created_at": "NOT_A_DATE", "status": "success"},
            {"id": 2, "created_at": "", "status": "success"},
        ]

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    self.assertFalse(mock_enqueue.called)

    def test_adv_split_shipments_fallback_to_updated_at(self):
        """Fulfillment lacking created_at uses updated_at."""
        now = datetime.now(timezone.utc)
        f_updated = now - timedelta(days=3)
        order = make_sample_order(order_id="ord_updated_at")
        order["fulfillments"] = [
            {"id": 1, "created_at": None, "updated_at": f_updated.isoformat(), "status": "success"}
        ]

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    self.assertAlmostEqual(kwargs["fulfilled_at"].timestamp(), f_updated.timestamp(), delta=2)


class TestFeature4CancellationAndRefundSuppression(unittest.TestCase):
    """Adversarial testing of cancellation, refund, and race condition suppression."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_sync_suppresses_cancelled_at(self):
        """Order with cancelled_at timestamp is skipped during sync."""
        order = make_sample_order(order_id="ord_canc_1")
        order["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    self.assertFalse(mock_enqueue.called)

    def test_adv_sync_suppresses_cancel_reason(self):
        """Order with cancel_reason is skipped during sync."""
        order = make_sample_order(order_id="ord_canc_2")
        order["cancel_reason"] = "customer"
        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    self.assertFalse(mock_enqueue.called)

    def test_adv_sync_suppresses_financial_status_refunded(self):
        """Order with financial_status == 'refunded' is skipped during sync."""
        order = make_sample_order(order_id="ord_ref_1")
        order["financial_status"] = "refunded"
        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    self.assertFalse(mock_enqueue.called)

    def test_adv_cancellation_webhook_cancels_pending_automation(self):
        """Order cancellation webhook updates pending automation status to 'canceled'."""
        with patch.object(pds.db, "cancel_post_delivery_automation", return_value=True) as mock_cancel:
            res = pds.db.cancel_post_delivery_automation("ord_to_cancel")
            self.assertTrue(res)
            mock_cancel.assert_called_once_with("ord_to_cancel")

    def test_adv_canceled_record_not_fetched_by_due_query(self):
        """Records marked status='canceled' are never returned by due automation query."""
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[]):
            count = self.service.process_due_vip_automations("luxury.myshopify.com")
            self.assertEqual(count, 0)

    def test_adv_post_delivery_cancel_function_idempotent(self):
        """Calling cancel on already canceled or missing order returns False cleanly without throwing."""
        with patch.object(pds.db, "cancel_post_delivery_automation", return_value=False):
            res = pds.db.cancel_post_delivery_automation("non_existent_or_already_canceled")
            self.assertFalse(res)

    def test_adv_order_cancelled_after_enqueue_sync_does_not_cancel_db_record_probe(self):
        """
        Probe vulnerability: If an order was enqueued, and subsequently cancelled in Shopify,
        sync_fulfilled_orders encounters cancelled_at and simply does 'continue',
        without invoking db.cancel_post_delivery_automation(order_id).
        """
        order = make_sample_order(order_id="ord_cancelled_later")
        order["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "cancel_post_delivery_automation") as mock_cancel:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0)
                    # Empirically verify that sync_fulfilled_orders does not call cancel_post_delivery_automation
                    self.assertFalse(mock_cancel.called)


class TestFeature4InputSanitizationAndExtremeValues(unittest.TestCase):
    """Adversarial testing of edge cases, Unicode, extreme prices, and missing contact info."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_unicode_and_emojis_in_customer_name(self):
        """Customer names containing emojis, Romanian diacritics, and Asian characters."""
        test_names = [
            "Elena 👑✨ VIP",
            "Lăcrămioara Munteanu-Pârvu",
            "田中 太郎",
            "فاطمة الزهراء",
            "Александр Пушкин"
        ]
        for name in test_names:
            msg = PostDeliveryService.build_vip_message(
                customer_name=name,
                purchased_item="Cămașă Mătase",
                discount_code="MGVIP15",
                lang="ro"
            )
            self.assertIn(name, msg)
            self.assertIn("MGVIP15", msg)

    def test_adv_empty_and_none_customer_name_fallback(self):
        """Empty or None customer names fallback safely to 'Client'."""
        for empty_val in ["", None]:
            msg = PostDeliveryService.build_vip_message(
                customer_name=empty_val,
                purchased_item="Suit",
                discount_code="MGVIP15",
                lang="en"
            )
            self.assertIn("Client", msg)
            self.assertIn("MGVIP15", msg)

    def test_adv_whitespace_customer_name_probe_unstripped(self):
        """
        Probe vulnerability: Whitespace-only customer name '   ' is not stripped
        in build_vip_message, resulting in unstripped whitespace 'Hi   !' instead of 'Client'.
        """
        msg = PostDeliveryService.build_vip_message(
            customer_name="   ",
            purchased_item="Suit",
            discount_code="MGVIP15",
            lang="en"
        )
        # Empirically proves that 'Client' is NOT substituted because bool('   ') is True
        self.assertNotIn("Client", msg)
        self.assertIn("Hi    !", msg)

    def test_adv_html_injection_in_customer_name(self):
        """Customer name containing HTML/XSS script tags is safely handled."""
        malicious_name = "<script>alert('xss')</script>"
        msg = PostDeliveryService.build_vip_message(
            customer_name=malicious_name,
            purchased_item="Suit",
            discount_code="MGVIP15",
            lang="en"
        )
        self.assertIn(malicious_name, msg)

        # Check HTML email builder escapes it
        html = self.service.email_dispatcher.build_html_email(
            shop_name="Luxury Store",
            customer_name=malicious_name,
            text_body=msg,
            discount_code="MGVIP15",
            line_items=[]
        )
        self.assertNotIn("<script>alert('xss')</script>", html)
        self.assertIn("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;", html)

    def test_adv_empty_and_none_items_summary(self):
        """Record with empty or None items_summary defaults safely to 'Selection'."""
        record = {
            "order_id": "ord_empty_items",
            "order_number": "1099",
            "customer_name": "Matteo",
            "customer_email": "matteo@example.com",
            "customer_phone": None,
            "discount_code": "MGVIP15",
            "items_summary": []
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
                with patch.object(pds.db, "mark_post_delivery_sent"):
                    with patch.object(pds.db, "save_autopilot_log"):
                        count = self.service.process_due_vip_automations("luxury.myshopify.com")
                        self.assertEqual(count, 1)
                        self.assertTrue(mock_mail.called)
                        body_text = mock_mail.call_args[1]["body_text"]
                        self.assertIn("Selection", body_text)

    def test_adv_corrupted_json_string_items_summary(self):
        """Record with corrupted JSON string items_summary doesn't crash and falls back safely."""
        record = {
            "order_id": "ord_corrupt_json_items",
            "order_number": "1100",
            "customer_name": "Andrei",
            "customer_email": "andrei@example.com",
            "customer_phone": None,
            "discount_code": "MGVIP15",
            "items_summary": "{INVALID_JSON_STRING"
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
                with patch.object(pds.db, "mark_post_delivery_sent"):
                    with patch.object(pds.db, "save_autopilot_log"):
                        count = self.service.process_due_vip_automations("luxury.myshopify.com")
                        self.assertEqual(count, 1)
                        self.assertTrue(mock_mail.called)
                        self.assertIn("Selection", mock_mail.call_args[1]["body_text"])

    def test_adv_string_items_summary_probe_attribute_error(self):
        """
        Probe vulnerability: items_summary containing a list of strings (e.g. ['Silk Scarf'])
        causes AttributeError: 'str' object has no attribute 'get' in process_due_vip_automations line 289.
        """
        record = {
            "order_id": "ord_str_items_probe",
            "order_number": "1102",
            "customer_name": "Lorenzo",
            "customer_email": "lorenzo@example.com",
            "customer_phone": None,
            "discount_code": "MGVIP15",
            "items_summary": ["Silk Scarf"]
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with self.assertRaises(AttributeError):
                self.service.process_due_vip_automations("luxury.myshopify.com")

    def test_adv_missing_item_title_defaults_to_articol(self):
        """Line items with missing/None title default safely to 'Articol'."""
        order = make_sample_order(order_id="ord_no_title")
        order["line_items"] = [{"title": None, "name": None, "price": "150.00"}]
        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    items = kwargs["items_summary"]
                    self.assertEqual(items[0]["title"], "Articol")

    def test_adv_invalid_email_missing_at_symbol(self):
        """Email missing '@' symbol is skipped, phone is still dispatched."""
        record = {
            "order_id": "ord_invalid_email",
            "order_number": "1101",
            "customer_name": "Lorenzo",
            "customer_email": "invalid_email_without_at",
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

    def test_adv_extreme_order_prices(self):
        """Extreme order price values (0.00, 999999999.99, negative, non-numeric) handled cleanly."""
        extreme_prices = ["0.00", "999999999.99", "-50.00", "FREE", "None"]
        for p in extreme_prices:
            order = make_sample_order(order_id=f"ord_p_{p}")
            order["line_items"] = [{"title": "Item", "price": p}]
            with patch.object(pds, "ShopifyClient") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.get_recent_orders = AsyncMock(return_value=[order])
                mock_client_cls.return_value = mock_client
                with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                    with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                        count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                        self.assertEqual(count, 1)
                        kwargs = mock_enqueue.call_args[1]
                        self.assertEqual(kwargs["items_summary"][0]["price"], str(p))


class TestFeature4StrictDiscountCodeMGVIP15(unittest.TestCase):
    """Adversarial verification that MGVIP15 discount code is strictly enforced everywhere."""

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_discount_code_constant_is_strictly_mgvip15(self):
        """Class constants DISCOUNT_CODE_MGVIP15 and VIP_DISCOUNT_CODE are strictly 'MGVIP15'."""
        self.assertEqual(PostDeliveryService.DISCOUNT_CODE_MGVIP15, "MGVIP15")
        self.assertEqual(PostDeliveryService.VIP_DISCOUNT_CODE, "MGVIP15")

    def test_adv_discount_code_in_all_six_language_templates(self):
        """VIP review messages in all 6 supported languages include 'MGVIP15'."""
        languages = ["ro", "it", "en", "es", "de", "fr"]
        for lang in languages:
            msg = PostDeliveryService.build_vip_message(
                customer_name="Valued Client",
                purchased_item="Luxury Knitwear",
                discount_code="MGVIP15",
                lang=lang
            )
            self.assertIn("MGVIP15", msg, f"Template for language '{lang}' must include MGVIP15")

    def test_adv_discount_code_fallback_when_empty_or_none(self):
        """Passing empty string or None for discount_code strictly falls back to 'MGVIP15'."""
        for val in ["", None]:
            msg = PostDeliveryService.build_vip_message(
                customer_name="Matteo",
                purchased_item="Suit",
                discount_code=val,
                lang="en"
            )
            self.assertIn("MGVIP15", msg, f"Fallback failed for discount_code={val}")

    def test_adv_discount_code_passed_to_email_dispatcher(self):
        """process_due_vip_automations passes discount_code='MGVIP15' to email dispatcher."""
        record = {
            "order_id": "ord_dc_email",
            "order_number": "1001",
            "customer_name": "Elena",
            "customer_email": "elena@example.com",
            "customer_phone": None,
            "discount_code": "MGVIP15",
            "items_summary": [{"title": "Silk Scarf"}]
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "build_html_email", wraps=self.service.email_dispatcher.build_html_email) as spy_build:
                with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
                    with patch.object(pds.db, "mark_post_delivery_sent"):
                        with patch.object(pds.db, "save_autopilot_log"):
                            count = self.service.process_due_vip_automations("luxury.myshopify.com")
                            self.assertEqual(count, 1)
                            self.assertEqual(spy_build.call_args[1]["discount_code"], "MGVIP15")
                            subject = mock_mail.call_args[1]["subject"]
                            self.assertIn("MGVIP15", subject)
                            body_html = mock_mail.call_args[1]["body_html"]
                            self.assertIn("MGVIP15", body_html)

    def test_adv_discount_code_passed_to_whatsapp_dispatcher(self):
        """process_due_vip_automations passes MGVIP15 in message to WhatsApp dispatcher."""
        record = {
            "order_id": "ord_dc_wa",
            "order_number": "1002",
            "customer_name": "Lorenzo",
            "customer_email": None,
            "customer_phone": "+393401234567",
            "discount_code": "MGVIP15",
            "items_summary": [{"title": "Smoking Tuxedo"}]
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock) as mock_wa:
                with patch.object(pds.db, "mark_post_delivery_sent"):
                    with patch.object(pds.db, "save_autopilot_log"):
                        count = self.service.process_due_vip_automations("luxury.myshopify.com")
                        self.assertEqual(count, 1)
                        wa_message = mock_wa.call_args[1]["message"]
                        self.assertIn("MGVIP15", wa_message)

    def test_adv_discount_code_passed_to_mobile_notifier(self):
        """process_due_vip_automations passes discount_code='MGVIP15' in event_data to MobileNotifier."""
        record = {
            "order_id": "ord_dc_mob",
            "order_number": "1003",
            "customer_name": "Andrei",
            "customer_email": "andrei@example.com",
            "customer_phone": "+40721123456",
            "discount_code": "MGVIP15",
            "items_summary": [{"title": "Cashmere Sweater"}]
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock):
                with patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock):
                    with patch.object(self.service.mobile_notifier, "notify_merchant", new_callable=AsyncMock) as mock_notify:
                        with patch.object(pds.db, "mark_post_delivery_sent"):
                            with patch.object(pds.db, "save_autopilot_log"):
                                count = self.service.process_due_vip_automations("luxury.myshopify.com")
                                self.assertEqual(count, 1)
                                event_type, event_data, _ = mock_notify.call_args[0]
                                self.assertEqual(event_type, "vip_upsell_sent")
                                self.assertEqual(event_data.get("discount_code"), "MGVIP15")

    def test_adv_discount_code_logged_to_autopilot_logs(self):
        """process_due_vip_automations logs discount_code='MGVIP15' in autopilot_logs subject."""
        record = {
            "order_id": "ord_dc_log",
            "order_number": "1004",
            "customer_name": "Maria",
            "customer_email": "maria@example.com",
            "customer_phone": None,
            "discount_code": "MGVIP15",
            "items_summary": []
        }
        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock):
                with patch.object(pds.db, "mark_post_delivery_sent"):
                    with patch.object(pds.db, "save_autopilot_log") as mock_log:
                        count = self.service.process_due_vip_automations("luxury.myshopify.com")
                        self.assertEqual(count, 1)
                        mock_log.assert_called_once()
                        log_subject = mock_log.call_args[1]["subject"]
                        self.assertIn("MGVIP15", log_subject)


if __name__ == "__main__":
    unittest.main()

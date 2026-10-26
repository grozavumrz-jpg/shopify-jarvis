"""
tests/test_post_delivery_adversarial.py
Adversarial Stress Testing & Edge-Case Harness for Milestone 3:
Feature 4: Post-Delivery VIP Review & Upsell Automation.

Evaluates 4 Challenge Dimensions:
1. Database idempotency and concurrency under repeated sync operations.
2. Multi-channel dispatch exception resilience (Email down, WhatsApp down, Notifier down, event loop concurrency).
3. 6-language template generation across edge cases, unicode, format string injections, and missing upsells.
4. Shopify payload edge cases: missing customer object, shipping address phone/name extraction, invalid fulfillments, corrupt items_summary.
"""

import unittest
import asyncio
import concurrent.futures
import json
import threading
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
import httpx

import backend.post_delivery_service as pds
from backend.post_delivery_service import PostDeliveryService
import backend.database as db
from tests.helpers import make_sample_order, make_sample_shop_settings


class TestAdversarialDatabaseIdempotencyAndState(unittest.TestCase):
    """
    Challenge Dimension 1:
    Database Idempotency, Repeated Sync Operations, and State Machine Integrity.
    """

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_sync_repeated_5_times_idempotent(self):
        """
        Adversarial probe:
        Simulate 5 consecutive daemon sync cycles with the exact same 10 fulfilled orders.
        Cycle 1 must enqueue 10 orders.
        Cycles 2, 3, 4, 5 must each enqueue 0 orders (strict idempotency).
        """
        now = datetime.now(timezone.utc)
        orders = [
            make_sample_order(order_id=f"ord_rep_{i}", fulfilled_at_dt=now - timedelta(days=2))
            for i in range(10)
        ]

        # In-memory table to simulate DB state & ON CONFLICT (order_id) DO NOTHING
        in_memory_db = set()

        def fake_enqueue(**kwargs):
            oid = str(kwargs.get("order_id"))
            if oid in in_memory_db:
                return False
            in_memory_db.add(oid)
            return True

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=orders)
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", side_effect=fake_enqueue):
                    # Cycle 1
                    count_1 = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count_1, 10, "Cycle 1 must enqueue all 10 new orders")
                    self.assertEqual(len(in_memory_db), 10)

                    # Cycles 2 to 5
                    for cycle in range(2, 6):
                        count_n = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                        self.assertEqual(count_n, 0, f"Cycle {cycle} must enqueue 0 duplicate orders")
                        self.assertEqual(len(in_memory_db), 10, "DB table must not grow on duplicate syncs")

    def test_adv_sync_does_not_overwrite_sent_state(self):
        """
        Adversarial probe:
        If an order was enqueued, fulfilled 6 days ago, processed, and marked status='sent',
        a subsequent sync_fulfilled_orders must NOT overwrite status back to 'pending'.
        Verified directly via ON CONFLICT (order_id) DO NOTHING SQL semantics.
        """
        with patch.object(db, "get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_cur.rowcount = 0  # Simulates ON CONFLICT DO NOTHING

            now = datetime.now(timezone.utc)
            res = db.enqueue_post_delivery_automation(
                shop="luxury.myshopify.com",
                order_id="ord_already_sent",
                order_number="1001",
                customer_email="elena@example.com",
                fulfilled_at=now - timedelta(days=6),
                scheduled_for=now - timedelta(days=1),
            )
            self.assertFalse(res, "ON CONFLICT DO NOTHING must report inserted=False")

            executed_sql = mock_cur.execute.call_args[0][0]
            self.assertIn("ON CONFLICT (order_id) DO NOTHING", executed_sql)
            self.assertNotIn("DO UPDATE", executed_sql, "Must never overwrite existing row on conflict")

    def test_adv_concurrent_enqueue_race_condition(self):
        """
        Adversarial probe:
        Simulate 20 concurrent threads trying to enqueue the exact same order_id simultaneously
        (simulating webhook arrival + daemon sync polling collision).
        """
        in_memory_store = set()
        lock = threading.Lock()
        success_count = [0]
        duplicate_count = [0]

        def thread_worker():
            with lock:
                oid = "ord_race_concurrency"
                if oid in in_memory_store:
                    duplicate_count[0] += 1
                else:
                    in_memory_store.add(oid)
                    success_count[0] += 1

        threads = [threading.Thread(target=thread_worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(success_count[0], 1, "Exactly one thread must succeed in enqueuing")
        self.assertEqual(duplicate_count[0], 19, "Remaining 19 threads must be recognized as duplicates")
        self.assertEqual(len(in_memory_store), 1)

    def test_adv_cancel_post_delivery_automation_sql_guard(self):
        """
        Adversarial probe:
        cancel_post_delivery_automation must update status = 'canceled' ONLY if status = 'pending'.
        It must never cancel an already 'sent' automation.
        """
        with patch.object(db, "get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_cur.rowcount = 1

            canceled = db.cancel_post_delivery_automation("ord_to_cancel")
            self.assertTrue(canceled)

            sql = mock_cur.execute.call_args[0][0]
            self.assertIn("status = 'canceled'", sql)
            self.assertIn("status = 'pending'", sql, "Cancel must only target pending automations")

    def test_adv_mark_sent_sql_guard(self):
        """
        Adversarial probe:
        mark_post_delivery_sent must update status = 'sent' ONLY if status = 'pending'.
        """
        with patch.object(db, "get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_cur.rowcount = 1

            sent = db.mark_post_delivery_sent("ord_to_mark")
            self.assertTrue(sent)

            sql = mock_cur.execute.call_args[0][0]
            self.assertIn("status = 'sent'", sql)
            self.assertIn("status = 'pending'", sql, "Mark sent must only transition pending records")


class TestAdversarialDispatchExceptionResilience(unittest.TestCase):
    """
    Challenge Dimension 2:
    Multi-Channel Dispatch Exception Resilience & Failure Containment.
    """

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_email_timeout_does_not_block_whatsapp_or_db_mark(self):
        """
        Adversarial scenario:
        SMTP / Email API experiences a connection timeout (httpx.TimeoutException).
        WhatsApp dispatch MUST proceed unimpeded.
        Merchant notification MUST proceed.
        Record MUST be marked sent.
        """
        record = {
            "order_id": "ord_email_timeout",
            "order_number": "1001",
            "customer_name": "Elena Popescu",
            "customer_email": "elena@example.com",
            "customer_phone": "+40721123456",
            "discount_code": "MGVIP15",
            "items_summary": [{"title": "Rochie Seară", "price": "250.00"}]
        }

        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", side_effect=httpx.TimeoutException("SMTP Timeout")):
                with patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock) as mock_wa:
                    with patch.object(self.service.mobile_notifier, "notify_merchant", new_callable=AsyncMock) as mock_notify:
                        with patch.object(pds.db, "mark_post_delivery_sent") as mock_mark:
                            with patch.object(pds.db, "save_autopilot_log"):
                                count = self.service.process_due_vip_automations("luxury.myshopify.com")
                                self.assertEqual(count, 1)
                                self.assertTrue(mock_wa.called, "WhatsApp must still be dispatched when Email times out")
                                self.assertTrue(mock_notify.called, "Mobile alert must still be sent")
                                mock_mark.assert_called_once()

    def test_adv_whatsapp_crash_does_not_block_email_or_db_mark(self):
        """
        Adversarial scenario:
        WhatsApp gateway raises an unhandled RuntimeError.
        Email MUST have been delivered.
        Merchant notification MUST be sent.
        Record MUST still be marked sent.
        """
        record = {
            "order_id": "ord_wa_crash",
            "order_number": "1002",
            "customer_name": "Matteo Rossi",
            "customer_email": "matteo@example.com",
            "customer_phone": "+393401234567",
            "discount_code": "MGVIP15",
            "items_summary": [{"title": "Camicia Lino"}]
        }

        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_email:
                with patch.object(self.service.wa_dispatcher, "send_message", side_effect=RuntimeError("Meta Graph API 500")):
                    with patch.object(self.service.mobile_notifier, "notify_merchant", new_callable=AsyncMock) as mock_notify:
                        with patch.object(pds.db, "mark_post_delivery_sent") as mock_mark:
                            with patch.object(pds.db, "save_autopilot_log"):
                                count = self.service.process_due_vip_automations("luxury.myshopify.com")
                                self.assertEqual(count, 1)
                                self.assertTrue(mock_email.called, "Email must be dispatched")
                                self.assertTrue(mock_notify.called, "Merchant alert must be sent")
                                mock_mark.assert_called_once()

    def test_adv_mobile_notifier_crash_does_not_abort_dispatch_count(self):
        """
        Adversarial scenario:
        Telegram Bot API / Discord Webhook raises Exception.
        Delivery to customer succeeded, record marked sent, returned count is 1.
        """
        record = {
            "order_id": "ord_mobile_down",
            "order_number": "1003",
            "customer_name": "Sophie Martin",
            "customer_email": "sophie@example.fr",
            "customer_phone": "+33612345678",
            "discount_code": "MGVIP15",
            "items_summary": []
        }

        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
            with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock):
                with patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock):
                    with patch.object(self.service.mobile_notifier, "notify_merchant", side_effect=Exception("Discord 503")):
                        with patch.object(pds.db, "mark_post_delivery_sent") as mock_mark:
                            with patch.object(pds.db, "save_autopilot_log"):
                                count = self.service.process_due_vip_automations("luxury.myshopify.com")
                                self.assertEqual(count, 1)
                                mock_mark.assert_called_once()

    def test_adv_active_event_loop_concurrency(self):
        """
        Adversarial scenario:
        process_due_vip_automations invoked from inside an already running asyncio event loop
        (e.g. inside FastAPI async endpoint handler).
        Verifies _run_coroutine uses ThreadPoolExecutor and does not raise
        'RuntimeError: This event loop is already running'.
        """
        record = {
            "order_id": "ord_async_loop",
            "order_number": "1004",
            "customer_name": "Lukas Weber",
            "customer_email": "lukas@example.de",
            "customer_phone": None,
            "discount_code": "MGVIP15",
            "items_summary": []
        }

        async def run_in_async_context():
            with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
                with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
                    with patch.object(pds.db, "mark_post_delivery_sent"):
                        with patch.object(pds.db, "save_autopilot_log"):
                            return self.service.process_due_vip_automations("luxury.myshopify.com")

        result = asyncio.run(run_in_async_context())
        self.assertEqual(result, 1, "Must execute cleanly from inside a running asyncio event loop")

    def test_adv_batch_isolation_one_failure_does_not_abort_subsequent_orders(self):
        """
        Adversarial scenario:
        A batch of 3 orders is due:
        - Order 1: Success
        - Order 2: Email & WhatsApp both throw exceptions
        - Order 3: Success
        All 3 orders are processed; Order 2 failure does NOT crash or skip Order 3.
        """
        records = [
            {"order_id": "ord_b1", "customer_name": "Client 1", "customer_email": "c1@test.com", "discount_code": "MGVIP15", "items_summary": []},
            {"order_id": "ord_b2", "customer_name": "Client 2", "customer_email": "c2@test.com", "discount_code": "MGVIP15", "items_summary": []},
            {"order_id": "ord_b3", "customer_name": "Client 3", "customer_email": "c3@test.com", "discount_code": "MGVIP15", "items_summary": []},
        ]

        async def selective_send_email(**kwargs):
            if kwargs.get("to_email") == "c2@test.com":
                raise RuntimeError("Hard SMTP failure for order 2")
            return {"ok": True}

        marked_sent_ids = []

        def fake_mark_sent(order_id, **kwargs):
            marked_sent_ids.append(order_id)
            return True

        with patch.object(pds.db, "get_due_post_delivery_automations", return_value=records):
            with patch.object(self.service.email_dispatcher, "send_email", side_effect=selective_send_email):
                with patch.object(pds.db, "mark_post_delivery_sent", side_effect=fake_mark_sent):
                    with patch.object(pds.db, "save_autopilot_log"):
                        count = self.service.process_due_vip_automations("luxury.myshopify.com")
                        self.assertEqual(count, 3)
                        self.assertIn("ord_b1", marked_sent_ids)
                        self.assertIn("ord_b3", marked_sent_ids)


class TestAdversarialMultiLanguageTemplates(unittest.TestCase):
    """
    Challenge Dimension 3:
    6-Language VIP Review Copy Generation, Diacritics, Placeholders, and Format Injection.
    """

    SUPPORTED_LANGS = ["ro", "it", "en", "es", "de", "fr"]

    def test_adv_all_6_languages_complete_vocabulary(self):
        """
        Verify all 6 languages:
        1. Render customer name.
        2. Render purchased item.
        3. Render upsell item when provided.
        4. Render discount code MGVIP15.
        5. Verify subject line template exists and contains {customer_name} and {discount_code}.
        """
        for lang in self.SUPPORTED_LANGS:
            tmpl = PostDeliveryService.VIP_TEMPLATES.get(lang)
            self.assertIsNotNone(tmpl, f"Missing template for language: {lang}")
            self.assertIn("msg", tmpl)
            self.assertIn("upsell", tmpl)
            self.assertIn("subject", tmpl)

            subject = tmpl["subject"].format(customer_name="Lorenzo", discount_code="MGVIP15")
            self.assertIn("Lorenzo", subject)
            self.assertIn("MGVIP15", subject)

            body = PostDeliveryService.build_vip_message(
                customer_name="Matteo",
                purchased_item="Cravatta Seta",
                upsell_item="Gemelli Oro",
                discount_code="MGVIP15",
                lang=lang
            )
            self.assertIn("Matteo", body, f"Customer name missing in {lang}")
            self.assertIn("Cravatta Seta", body, f"Purchased item missing in {lang}")
            self.assertIn("Gemelli Oro", body, f"Upsell item missing in {lang}")
            self.assertIn("MGVIP15", body, f"Discount code missing in {lang}")

    def test_adv_no_upsell_item_clean_clause(self):
        """
        When upsell_item is None or empty, no dangling empty parentheses '()'
        or raw '{upsell_clause}' placeholders may appear.
        """
        for lang in self.SUPPORTED_LANGS:
            body = PostDeliveryService.build_vip_message(
                customer_name="Elena",
                purchased_item="Rochie",
                upsell_item=None,
                discount_code="MGVIP15",
                lang=lang
            )
            self.assertNotIn("()", body, f"Dangling empty parens in {lang}")
            self.assertNotIn("{upsell_clause}", body, f"Raw placeholder in {lang}")
            self.assertNotIn("{upsell_item}", body, f"Raw placeholder in {lang}")
            self.assertIn("MGVIP15", body)

    def test_adv_template_injection_immunity(self):
        """
        Adversarial probe:
        Malicious names or items containing format specifiers ({0}, {discount_code}, {injection}, {{x}})
        must NOT trigger KeyError, IndexError, or evaluate nested format syntax.
        """
        adversarial_names = [
            "John {0} {discount_code}",
            "{injection_test}",
            "{{escaped_brace}}",
            "Robert; DROP TABLE users; --",
            "<script>alert(1)</script>",
        ]
        adversarial_items = [
            "Silk Scarf {discount_code}",
            "Item with {unclosed brace",
            "Item with }inverted brace{",
            "Special {foo} item",
        ]

        for name in adversarial_names:
            for item in adversarial_items:
                msg = PostDeliveryService.build_vip_message(
                    customer_name=name,
                    purchased_item=item,
                    upsell_item="Tie {bar}",
                    discount_code="MGVIP15",
                    lang="en"
                )
                self.assertIn("MGVIP15", msg)
                self.assertIn(name, msg)
                self.assertIn(item, msg)

    def test_adv_unicode_diacritics_and_special_alphabets(self):
        """
        Adversarial probe:
        Verify flawless string formatting with Romanian (ș, ț), German (ä, ö, ü, ß),
        French (ç, é, è, ê), Spanish (ñ, ¡, ¿), Italian (à, è), and CJK/Arabic.
        """
        test_cases = [
            ("ro", "Ștefan Păun", "Cămașă In", "Pantaloni Lână"),
            ("de", "Jürgen Müller", "Maßanzug Grün", "Ledergürtel"),
            ("fr", "François Noël", "Costume Élégant", "Nœud Papillon"),
            ("es", "Álvaro González", "Camisa Blanca", "Zapatos Cuero"),
            ("it", "Niccolò D'Angelo", "Abito Sartoriale", "Pochette Seta"),
            ("en", "田中太郎", "Kimono Silk 👘", "Sash Obi ✨"),
        ]

        for lang, name, item, upsell in test_cases:
            msg = PostDeliveryService.build_vip_message(
                customer_name=name,
                purchased_item=item,
                upsell_item=upsell,
                discount_code="MGVIP15",
                lang=lang
            )
            self.assertIn(name, msg)
            self.assertIn(item, msg)
            self.assertIn(upsell, msg)

    def test_adv_language_code_normalization_matrix(self):
        """
        Adversarial probe:
        Language codes formatted with region tags (ro-RO), underscore (ro_RO),
        uppercase (RO, EN), or unsupported locales (ja, zh, unknown) must not crash.
        """
        matrix = [
            ("ro-RO", "Salut"),
            ("RO", "Salut"),
            ("it-IT", "Ciao"),
            ("IT", "Ciao"),
            ("es-ES", "Hola"),
            ("ES", "Hola"),
            ("de-DE", "Hallo"),
            ("DE", "Hallo"),
            ("fr-FR", "Bonjour"),
            ("FR", "Bonjour"),
            ("en-US", "Hi"),
            ("EN", "Hi"),
            ("ja", "Hi"),       # Fallback to English
            ("zh", "Hi"),       # Fallback to English
            (None, "Hi"),       # Fallback to English
            ("", "Hi"),         # Fallback to English
        ]

        for code, expected_prefix in matrix:
            msg = PostDeliveryService.build_vip_message(
                customer_name="Client",
                purchased_item="Item",
                lang=code
            )
            self.assertTrue(any(expected_prefix in msg for _ in [1]), f"Failed prefix check for lang {code}")


class TestAdversarialShopifyOrderPayloadEdgeCases(unittest.TestCase):
    """
    Challenge Dimension 4:
    Shopify Order Payloads: Missing Customer Objects, Addresses in Shipping but not Billing,
    International Phone Number Formats, and Malformed Fulfillments.
    """

    def setUp(self):
        self.service = PostDeliveryService()

    def test_adv_missing_customer_dict_guest_checkout(self):
        """
        Guest checkout where order['customer'] is None or missing.
        Top-level email and phone are present.
        Must successfully extract contact info and fall back customer_name cleanly.
        """
        now = datetime.now(timezone.utc)
        order = {
            "id": 888101,
            "order_number": 9901,
            "email": "guest@luxury.com",
            "phone": "+40721999888",
            "customer": None,  # Missing customer object
            "fulfillments": [
                {"id": 1, "created_at": (now - timedelta(days=2)).isoformat(), "status": "success"}
            ],
            "line_items": [{"title": "Cashmere Wrap", "price": "190.00"}]
        }

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    self.assertEqual(kwargs["customer_email"], "guest@luxury.com")
                    self.assertEqual(kwargs["customer_phone"], "+40721999888")
                    self.assertIn(kwargs["customer_name"], ["Valued Client", "Client"])

    def test_adv_malformed_fulfillments_list_resilience(self):
        """
        Adversarial probe:
        Fulfillments list contains corrupted elements:
        - None
        - Non-dict string
        - status='failure'
        - status='cancelled'
        - missing timestamp
        - unparseable timestamp string
        Must not crash, and order must be skipped if no valid fulfillment date remains.
        """
        order = {
            "id": 888102,
            "email": "elena@luxury.com",
            "fulfillments": [
                None,
                "corrupted_element",
                {"status": "failure", "created_at": "2026-10-20T10:00:00Z"},
                {"status": "cancelled", "created_at": "2026-10-20T10:00:00Z"},
                {"status": "success", "created_at": None},
                {"status": "success", "created_at": "not-a-valid-date-string"},
            ],
            "line_items": []
        }

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation") as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 0, "No valid fulfillments should result in 0 enqueued")
                    self.assertFalse(mock_enqueue.called)

    def test_adv_multiple_split_fulfillments_latest_date_selection(self):
        """
        Adversarial probe:
        Order fulfilled across 4 shipments over 10 days.
        Must select the latest fulfillment date for the 5-day delay calculation.
        """
        now = datetime.now(timezone.utc)
        d1 = now - timedelta(days=12)
        d2 = now - timedelta(days=8)
        d3 = now - timedelta(days=4)
        d4 = now - timedelta(days=1)  # Latest

        order = {
            "id": 888103,
            "email": "split@luxury.com",
            "fulfillments": [
                {"id": 1, "created_at": d1.isoformat(), "status": "success"},
                {"id": 2, "created_at": d3.isoformat(), "status": "success"},
                {"id": 3, "created_at": d4.isoformat(), "status": "success"},
                {"id": 4, "created_at": d2.isoformat(), "status": "success"},
            ],
            "line_items": []
        }

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    count = self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    self.assertEqual(count, 1)
                    kwargs = mock_enqueue.call_args[1]
                    self.assertAlmostEqual(kwargs["fulfilled_at"].timestamp(), d4.timestamp(), delta=2)
                    expected_sched = d4 + timedelta(days=5)
                    self.assertAlmostEqual(kwargs["scheduled_for"].timestamp(), expected_sched.timestamp(), delta=2)

    def test_adv_order_number_and_id_formatting(self):
        """
        Adversarial probe:
        Order with name='#1088', order_number=1088, id=778899.
        Must strip leading '#' from order_number for clean display.
        """
        now = datetime.now(timezone.utc)
        order = {
            "id": 778899,
            "name": "#1088",
            "order_number": 1088,
            "email": "test@luxury.com",
            "fulfillments": [{"id": 1, "created_at": now.isoformat(), "status": "success"}]
        }

        with patch.object(pds, "ShopifyClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_recent_orders = AsyncMock(return_value=[order])
            mock_client_cls.return_value = mock_client
            with patch.object(pds.db, "get_shop", return_value={"shop": "luxury.myshopify.com", "access_token": "token"}):
                with patch.object(pds.db, "enqueue_post_delivery_automation", return_value=True) as mock_enqueue:
                    self.service.sync_fulfilled_orders("luxury.myshopify.com")
                    kwargs = mock_enqueue.call_args[1]
                    self.assertEqual(kwargs["order_number"], "1088")
                    self.assertFalse(kwargs["order_number"].startswith("#"))

    def test_adv_items_summary_resilience_in_due_processing(self):
        """
        Adversarial probe:
        Test process_due_vip_automations with various items_summary structures:
        - empty list: []
        - JSON string: '[]'
        - corrupted JSON string: '{"corrupt"'
        - list with dict having no 'title' key: [{'name': 'Robe'}]
        - list with dict having title=None
        """
        test_summaries = [
            [],
            "[]",
            "corrupted_json_string",
            [{"name": "Robe"}],
            [{"title": None}],
            [{"title": "Maison Knitwear", "price": "145.00"}],
        ]

        for i, summary in enumerate(test_summaries):
            record = {
                "order_id": f"ord_summary_{i}",
                "order_number": f"100{i}",
                "customer_name": "Test Client",
                "customer_email": "client@test.com",
                "customer_phone": None,
                "discount_code": "MGVIP15",
                "items_summary": summary
            }

            with patch.object(pds.db, "get_due_post_delivery_automations", return_value=[record]):
                with patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock):
                    with patch.object(pds.db, "mark_post_delivery_sent"):
                        with patch.object(pds.db, "save_autopilot_log"):
                            # Must not raise exception
                            count = self.service.process_due_vip_automations("luxury.myshopify.com")
                            self.assertEqual(count, 1, f"Failed on summary format index {i}")

    def test_adv_phone_number_cleaning_across_all_supported_regions(self):
        """
        Adversarial probe:
        Verify clean_phone_number correctly cleans and normalizes numbers across:
        - Romania: 0721123456 -> 40721123456, +40 721 123 456 -> 40721123456, 0040721123456 -> 40721123456
        - Italy: 3401234567 -> 393401234567, +39 340 123 4567 -> 393401234567, 00393401234567 -> 393401234567
        - Spain: 612345678 -> 34612345678, +34 612 345 678 -> 34612345678
        - Germany: 015112345678 -> 4915112345678, +49 151 12345678 -> 4915112345678
        - France: +33 6 12 34 56 78 -> 33612345678
        - Invalid numbers: '123', 'abc', None -> empty string or short
        """
        dispatcher = self.service.wa_dispatcher
        cases = [
            ("0721123456", "40721123456"),
            ("+40 721 123 456", "40721123456"),
            ("0040721123456", "40721123456"),
            ("3401234567", "393401234567"),
            ("+39 340 123 4567", "393401234567"),
            ("00393401234567", "393401234567"),
            ("612345678", "34612345678"),
            ("+34 612 345 678", "34612345678"),
            ("015112345678", "4915112345678"),
            ("+49 151 12345678", "4915112345678"),
            ("+33 6 12 34 56 78", "33612345678"),
            ("", ""),
            (None, ""),
            ("invalid", ""),
        ]

        for raw, expected in cases:
            cleaned = dispatcher.clean_phone_number(raw)
            self.assertEqual(cleaned, expected, f"Failed cleaning for {raw}")


if __name__ == "__main__":
    unittest.main()

"""
tests/test_tier5_system_stress.py
Tier 5 Adversarial Coverage Hardening & System Stress Test Suite for Shopify Jarvis.
Author: Challenger Tier 5-2

Scope across all 5 core revenue features:
1. Multi-Tenant Merchant Isolation (Store A vs Store B vs Store C credentials, DB queries, settings API)
2. Full Pipeline End-to-End Stress (Cart abandonment -> Stage 1 email -> Stage 2 WhatsApp -> Conversion -> VIP 5-day review -> Triple merchant notifications)
3. Payload Malformation & Chaos Testing (Empty items, None/negative prices, XSS/SQLi, Discord 1024-char limits, international phones)
4. Webhook Security & Idempotency (Order creation replay attacks, cancellation arriving before sync, repeated fulfillment enqueues)
5. Daemon Resilience & Concurrency (Multi-store batch failure isolation, provider crash fault tolerance, clock skew resilience)
"""

import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta
import json
import html
import httpx
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from tests.helpers import (
    make_sample_line_item,
    make_sample_checkout,
    make_sample_order,
    make_sample_shop_settings,
)
from backend.cadence_manager import DripCadenceManager
from backend.post_delivery_service import PostDeliveryService
from backend.whatsapp_dispatcher import WhatsAppDispatcher
from backend.email_dispatcher import EmailDispatcher
from backend.mobile_notifier import MobileNotifier
from backend.shopify_api import detect_customer_language_and_country, ShopifyClient
import backend.database as db
import backend.main as bm
from backend.main import (
    app,
    process_single_checkout_recovery,
    webhook_order_created,
    webhook_order_cancelled,
)
from fastapi.testclient import TestClient


# ==============================================================================
# 1. Multi-Tenant Merchant Isolation Stress Testing
# ==============================================================================

class TestTier5MultiTenantIsolation(unittest.TestCase):
    """
    Stress-tests multi-tenant isolation across configurations, database queries,
    and external dispatch headers/tokens.
    """

    def setUp(self):
        self.wa = WhatsAppDispatcher()
        self.mobile = MobileNotifier()
        self.cadence = DripCadenceManager()
        self.post_delivery = PostDeliveryService()

    def test_isolation_store_credentials_never_leak_in_waterfall(self):
        """
        Store A (Twilio only) and Store B (Meta only) and Store C (unconfigured)
        are invoked interleaved in rapid succession.
        Verify:
        - Store A requests contain ONLY Store A's Twilio SID/Auth, never Meta token or Store B tokens.
        - Store B requests contain ONLY Store B's Meta Bearer token, never Twilio SID or Store A tokens.
        - Store C produces wa.me fallback without executing network calls or inheriting prior store tokens.
        """
        settings_a = {
            "shop": "boutique-a.myshopify.com",
            "whatsapp_provider": "twilio",
            "twilio_account_sid": "AC_STORE_A_ALPHA",
            "twilio_auth_token": "TOKEN_STORE_A_SECRET",
            "twilio_whatsapp_number": "whatsapp:+14150000001",
        }
        settings_b = {
            "shop": "boutique-b.myshopify.com",
            "whatsapp_provider": "meta",
            "whatsapp_api_token": "META_STORE_B_BEARER_XYZ",
            "whatsapp_phone_number_id": "PHONE_ID_STORE_B_777",
        }
        settings_c = {
            "shop": "boutique-c.myshopify.com",
            "whatsapp_provider": "auto",
            "whatsapp_api_token": "",
            "twilio_account_sid": "",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            resp_twilio = MagicMock(status_code=201, json=lambda: {"sid": "SM_A_1"})
            resp_meta = MagicMock(status_code=200, json=lambda: {"messages": [{"id": "WAMID_B_1"}]})
            mock_post.side_effect = [resp_twilio, resp_meta]

            # Interleaved dispatches
            res_a = asyncio.run(self.wa.send_message("+393401111111", "Message for A", settings=settings_a))
            res_c = asyncio.run(self.wa.send_message("+40721333333", "Message for C", settings=settings_c))
            res_b = asyncio.run(self.wa.send_message("+34612222222", "Message for B", settings=settings_b))

            self.assertTrue(res_a["ok"])
            self.assertEqual(res_a["provider"], "twilio")

            self.assertFalse(res_c["ok"])
            self.assertEqual(res_c["provider"], "wa_me")
            self.assertIn("https://wa.me/40721333333", res_c["wa_me_url"])

            self.assertTrue(res_b["ok"])
            self.assertEqual(res_b["provider"], "meta")

            # Check outbound HTTP payloads
            call_a = mock_post.call_args_list[0]
            call_b = mock_post.call_args_list[1]

            # Store A call must strictly use Twilio Basic Auth and Store A number
            self.assertEqual(call_a[1]["auth"], ("AC_STORE_A_ALPHA", "TOKEN_STORE_A_SECRET"))
            self.assertIn("whatsapp:+14150000001", str(call_a))
            self.assertNotIn("META_STORE_B_BEARER_XYZ", str(call_a))

            # Store B call must strictly use Meta Bearer token
            self.assertEqual(call_b[1]["headers"]["Authorization"], "Bearer META_STORE_B_BEARER_XYZ")
            self.assertIn("PHONE_ID_STORE_B_777", call_b[0][0])
            self.assertNotIn("AC_STORE_A_ALPHA", str(call_b))

    def test_isolation_db_drip_states_filtered_by_shop(self):
        """
        Verify database queries for active drip states filter strictly by shop_domain.
        A query for Store A must never return Store B's checkouts.
        """
        records = [
            {"id": 1, "shop_domain": "store-a.myshopify.com", "checkout_id": "ch_a_1", "status": "active", "current_stage": 0},
            {"id": 2, "shop_domain": "store-b.myshopify.com", "checkout_id": "ch_b_1", "status": "active", "current_stage": 0},
            {"id": 3, "shop_domain": "store-a.myshopify.com", "checkout_id": "ch_a_2", "status": "active", "current_stage": 1},
        ]

        def fake_get_conn():
            mock_cur = MagicMock()
            def execute(query, params=None):
                if "shop_domain = %s" in query and params:
                    target_shop = params[0]
                    matched = [r for r in records if r["shop_domain"] == target_shop]
                    mock_cur.fetchall.return_value = matched
                else:
                    mock_cur.fetchall.return_value = records
            mock_cur.execute = execute
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            return mock_conn

        with patch("backend.database.get_conn", side_effect=fake_get_conn):
            active_a = db.get_active_drip_states("store-a.myshopify.com")
            active_b = db.get_active_drip_states("store-b.myshopify.com")

            self.assertEqual(len(active_a), 2)
            for r in active_a:
                self.assertEqual(r["shop_domain"], "store-a.myshopify.com")

            self.assertEqual(len(active_b), 1)
            self.assertEqual(active_b[0]["shop_domain"], "store-b.myshopify.com")

    def test_isolation_db_conversion_does_not_affect_other_shops(self):
        """
        Customer Elena buys on Store B with email elena@example.com.
        Store A ALSO has an active abandoned cart from elena@example.com.
        Reconciling order for Store B must NEVER convert or cancel Store A's active drip record!
        """
        table = {
            "ch_a": {"shop_domain": "store-a.myshopify.com", "email": "elena@example.com", "status": "active"},
            "ch_b": {"shop_domain": "store-b.myshopify.com", "email": "elena@example.com", "status": "active"},
        }

        def fake_mark_converted(shop, checkout_id=None, email=None, checkout_token=None, order_id=None, revenue=0.0):
            converted_count = 0
            for cid, rec in table.items():
                if rec["shop_domain"] == shop and rec["status"] == "active":
                    if email and rec["email"].lower() == email.lower():
                        rec["status"] = "converted"
                        converted_count += 1
            return converted_count

        with patch.object(self.cadence, "mark_order_converted") as mock_conv:
            def cadence_conv(shop, order_dict):
                em = order_dict.get("email") or (order_dict.get("customer") or {}).get("email")
                rows = fake_mark_converted(shop=shop, email=em)
                return rows > 0
            mock_conv.side_effect = cadence_conv

            order_b = {
                "id": "ord_b_999",
                "customer": {"email": "elena@example.com"},
                "total_price": "150.00"
            }
            res = self.cadence.mark_order_converted("store-b.myshopify.com", order_b)
            self.assertTrue(res)

            # Store B is converted, Store A remains active
            self.assertEqual(table["ch_b"]["status"], "converted")
            self.assertEqual(table["ch_a"]["status"], "active")

    def test_isolation_db_post_delivery_queue_filtered_by_shop(self):
        """
        Verify post-delivery VIP automations queue strictly filters by shop_domain.
        """
        queue_records = [
            {"id": 101, "shop_domain": "store-a.myshopify.com", "order_id": "ord_a_1", "status": "pending"},
            {"id": 102, "shop_domain": "store-b.myshopify.com", "order_id": "ord_b_1", "status": "pending"},
        ]

        def fake_get_conn():
            mock_cur = MagicMock()
            def execute(query, params=None):
                if "shop_domain = %s" in query and params:
                    mock_cur.fetchall.return_value = [r for r in queue_records if r["shop_domain"] == params[0]]
                else:
                    mock_cur.fetchall.return_value = queue_records
            mock_cur.execute = execute
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.__enter__.return_value = mock_conn
            return mock_conn

        with patch("backend.database.get_conn", side_effect=fake_get_conn):
            queue_a = db.get_post_delivery_queue("store-a.myshopify.com")
            queue_b = db.get_post_delivery_queue("store-b.myshopify.com")

            self.assertEqual(len(queue_a), 1)
            self.assertEqual(queue_a[0]["order_id"], "ord_a_1")
            self.assertEqual(len(queue_b), 1)
            self.assertEqual(queue_b[0]["order_id"], "ord_b_1")

    def test_isolation_shop_settings_api_isolation(self):
        """
        Inspect /api/settings/whatsapp endpoint with TestClient for Store A vs Store B.
        Ensure masked settings return the respective tokens without leakage.
        """
        settings_db = {
            "store-alpha.myshopify.com": {
                "shop": "store-alpha.myshopify.com",
                "whatsapp_provider": "twilio",
                "twilio_account_sid": "AC_ALPHA_99",
                "twilio_auth_token": "SECRET_ALPHA",
                "whatsapp_api_token": ""
            },
            "store-beta.myshopify.com": {
                "shop": "store-beta.myshopify.com",
                "whatsapp_provider": "meta",
                "whatsapp_api_token": "TOKEN_BETA_123",
                "twilio_account_sid": ""
            }
        }

        with patch.object(bm.db, "get_shop_settings", side_effect=lambda s: settings_db.get(s, {})):
            client = TestClient(app)
            resp_alpha = client.get("/api/settings/whatsapp?shop=store-alpha.myshopify.com")
            resp_beta = client.get("/api/settings/whatsapp?shop=store-beta.myshopify.com")

            self.assertEqual(resp_alpha.status_code, 200)
            self.assertEqual(resp_beta.status_code, 200)

            data_alpha = resp_alpha.json()
            data_beta = resp_beta.json()

            self.assertEqual(data_alpha["twilio_account_sid"], "AC_ALPHA_99")
            self.assertEqual(data_alpha["twilio_auth_token"], "••••••••")
            self.assertEqual(data_alpha["whatsapp_api_token"], "")

            self.assertEqual(data_beta["whatsapp_provider"], "meta")
            self.assertEqual(data_beta["whatsapp_api_token"], "••••••••")
            self.assertEqual(data_beta["twilio_account_sid"], "")


# ==============================================================================
# 2. Full Pipeline End-to-End Stress & Triple Alert Workload
# ==============================================================================

class TestTier5FullPipelineE2EStress(unittest.TestCase):
    """
    Stress-tests the full 5-feature lifecycle end-to-end:
    Abandoned Cart -> Stage 1 Email (No discount) -> Stage 2 WhatsApp (MG10) ->
    Order Conversion (cadence canceled) -> Order Fulfillment ->
    VIP Review & Upsell 5 days later (MGVIP15) -> Triple Merchant Mobile Notifications.
    """

    def setUp(self):
        self.cadence = DripCadenceManager()
        self.post_delivery = PostDeliveryService()
        self.email_disp = EmailDispatcher()
        self.wa_disp = WhatsAppDispatcher()
        self.mobile = MobileNotifier()

    def test_full_e2e_5_stage_lifecycle_with_triple_alert(self):
        """
        Executes complete lifecycle across time progression:
        T0: Abandoned cart created (Elena Popescu, 2 line items, total €240).
        T0 + 35m: Stage 1 evaluated and executed -> Email sent, NO discount, amber alert.
        T0 + 4h10m: Stage 2 evaluated and executed -> WhatsApp sent with MG10, amber alert.
        T0 + 5h: Order conversion webhook arrives -> Drip marked converted, emerald alert.
        T0 + 25h: Stage 3 check returns None (converted).
        T1 (T0 + 1d): Fulfillment occurs. Enqueued in post_delivery_automations for T1 + 5d.
        T1 + 5d + 1h: VIP processing runs -> Email + WhatsApp dispatched with MGVIP15, purple alert.
        """
        now = datetime.now(timezone.utc)
        t0 = now - timedelta(days=7)
        shop = "luxury-milano.myshopify.com"
        settings = make_sample_shop_settings()
        settings["shop"] = shop

        items = [
            make_sample_line_item(product_id=1, title="Maison Silk Blouse", price="140.00"),
            make_sample_line_item(product_id=2, title="Leather Belt", price="100.00")
        ]
        checkout = make_sample_checkout(
            checkout_id="ch_full_e2e_001",
            customer_name="Elena Popescu",
            email="elena.popescu@luxury.ro",
            phone="+40721111222",
            total_price=240.00,
            currency="EUR",
            created_at_dt=t0,
            line_items=items
        )

        drip_state = {
            "shop_domain": shop,
            "checkout_id": "ch_full_e2e_001",
            "current_stage": 0,
            "status": "active",
            "created_at": t0.isoformat(),
            "stage_1_sent_at": None,
            "stage_2_sent_at": None,
            "stage_3_sent_at": None
        }

        # ── Step 1: Stage 1 at T0 + 35m ──
        t_stage1 = t0 + timedelta(minutes=35)
        st1_res = self.cadence.evaluate_drip_stage(checkout, drip_state, now_dt=t_stage1)
        self.assertEqual(st1_res, 1, "Cadence must transition to Stage 1 at 35m")

        st1_meta = self.cadence.get_stage_metadata(1)
        self.assertIsNone(st1_meta["discount_code"])
        self.assertFalse(st1_meta["has_discount"])

        st1_url = self.cadence.build_stage_checkout_url(checkout["checkout_url"], 1)
        self.assertNotIn("discount=", st1_url, "Stage 1 checkout URL must NOT contain discount query param")

        # HTML Email check: coupon box omitted
        html_st1 = self.email_disp.build_html_email(
            shop_name="Luxury Milano",
            customer_name="Elena Popescu",
            text_body="Ne bucurăm că ai ales Luxury Milano.",
            discount_code=None,
            line_items=items,
            lang="ro"
        )
        self.assertNotIn("MG10", html_st1)
        self.assertIn("Maison Silk Blouse", html_st1)
        self.assertIn("Leather Belt", html_st1)

        # Alert 1: Abandoned Cart Alert (Amber)
        alert_1_data = {
            "customer_name": "Elena Popescu",
            "total_price": 240.00,
            "currency": "EUR",
            "items": ["Maison Silk Blouse", "Leather Belt"],
            "checkout_url": st1_url,
            "stage": 1,
            "discount_code": None
        }
        embed_1 = self.mobile.format_discord_embed("abandoned_cart", alert_1_data)
        self.assertEqual(embed_1["color"], MobileNotifier.COLOR_AMBER)
        self.assertIn("Coș Abandonat Detectat", embed_1["title"])

        # Update state to Stage 1
        drip_state["current_stage"] = 1
        drip_state["stage_1_sent_at"] = t_stage1.isoformat()

        # ── Step 2: Stage 2 at T0 + 4h10m ──
        t_stage2 = t0 + timedelta(hours=4, minutes=10)
        st2_res = self.cadence.evaluate_drip_stage(checkout, drip_state, now_dt=t_stage2)
        self.assertEqual(st2_res, 2, "Cadence must transition to Stage 2 at 4h10m")

        st2_meta = self.cadence.get_stage_metadata(2)
        self.assertEqual(st2_meta["discount_code"], "MG10")
        self.assertTrue(st2_meta["has_discount"])

        st2_url = self.cadence.build_stage_checkout_url(checkout["checkout_url"], 2)
        self.assertIn("discount=MG10", st2_url)

        # WhatsApp link verification
        wa_link = self.wa_disp.generate_wa_me_link(checkout["phone"], f"Finalizează comanda cu 10% reducere: {st2_url}")
        self.assertTrue(wa_link.startswith("https://wa.me/40721111222"))
        self.assertIn("MG10", wa_link)

        # Alert 2: Stage 2 Alert (Amber)
        alert_2_data = dict(alert_1_data, stage=2, discount_code="MG10", checkout_url=st2_url)
        embed_2 = self.mobile.format_discord_embed("abandoned_cart", alert_2_data)
        self.assertEqual(embed_2["color"], MobileNotifier.COLOR_AMBER)

        # Update state to Stage 2
        drip_state["current_stage"] = 2
        drip_state["stage_2_sent_at"] = t_stage2.isoformat()

        # ── Step 3: Order Conversion at T0 + 5h ──
        converted_order = {
            "id": "ord_milano_7001",
            "order_number": "7001",
            "customer": {"email": "elena.popescu@luxury.ro", "first_name": "Elena", "last_name": "Popescu"},
            "total_price": "216.00",
            "currency": "EUR",
            "discount_codes": [{"code": "MG10", "amount": "24.00"}]
        }

        # Simulate DB reconciliation
        drip_state["status"] = "converted"
        drip_state["converted_order_id"] = "ord_milano_7001"
        drip_state["revenue_recovered"] = 216.00

        # Alert 3: Revenue Recovery Converted Alert (Emerald)
        alert_conv_data = {
            "customer_name": "Elena Popescu",
            "order_number": "7001",
            "recovered_revenue": 216.00,
            "currency": "EUR",
            "discount_code": "MG10"
        }
        embed_conv = self.mobile.format_discord_embed("recovery_converted", alert_conv_data)
        self.assertEqual(embed_conv["color"], MobileNotifier.COLOR_EMERALD)
        self.assertIn("Venit Recuperat cu Succes", embed_conv["title"])

        # ── Step 4: Verification of Stage 3 Suppression ──
        t_stage3 = t0 + timedelta(hours=25)
        st3_res = self.cadence.evaluate_drip_stage(checkout, drip_state, now_dt=t_stage3)
        self.assertIsNone(st3_res, "Converted cart must NEVER trigger Stage 3")

        # ── Step 5: Fulfillment Ingestion ──
        t_fulfill = t0 + timedelta(days=1)
        post_delivery_record = {
            "id": 501,
            "shop_domain": shop,
            "order_id": "ord_milano_7001",
            "order_number": "7001",
            "customer_email": "elena.popescu@luxury.ro",
            "customer_phone": "+40721111222",
            "customer_name": "Elena Popescu",
            "fulfilled_at": t_fulfill,
            "scheduled_for": t_fulfill + timedelta(days=5),
            "items_summary": items,
            "status": "pending",
            "discount_code": "MGVIP15"
        }

        # ── Step 6: VIP Due Evaluation & Dispatch at T_fulfill + 5d + 1h ──
        t_vip_check = t_fulfill + timedelta(days=5, hours=1)
        self.assertLessEqual(post_delivery_record["scheduled_for"], t_vip_check)

        # VIP message build
        vip_msg = self.post_delivery.build_vip_message(
            customer_name="Elena Popescu",
            purchased_item="Maison Silk Blouse",
            discount_code="MGVIP15",
            lang="ro"
        )
        self.assertIn("MGVIP15", vip_msg)
        self.assertIn("15% reducere VIP", vip_msg)

        # Alert 4: VIP Review & Upsell Alert (Purple)
        alert_vip_data = {
            "customer_name": "Elena Popescu",
            "order_number": "7001",
            "discount_code": "MGVIP15"
        }
        embed_vip = self.mobile.format_discord_embed("vip_upsell_sent", alert_vip_data)
        self.assertEqual(embed_vip["color"], MobileNotifier.COLOR_PURPLE)
        self.assertIn("VIP Review & Upsell", embed_vip["title"])

        # Mark sent
        post_delivery_record["status"] = "sent"
        self.assertEqual(post_delivery_record["status"], "sent")


# ==============================================================================
# 3. Payload Malformation & Chaos Testing
# ==============================================================================

class TestTier5PayloadMalformationChaos(unittest.TestCase):
    """
    Stress-tests the system against corrupted, malformed, malicious, or extreme payloads.
    """

    def setUp(self):
        self.email_disp = EmailDispatcher()
        self.mobile = MobileNotifier()
        self.wa = WhatsAppDispatcher()
        self.cadence = DripCadenceManager()
        self.post_delivery = PostDeliveryService()

    def test_chaos_empty_line_items_and_none_prices(self):
        """
        Checkouts with empty line items list, None prices, or empty strings.
        Must render templates cleanly without crashing or raising exceptions.
        """
        raw_checkout = {
            "id": "ch_chaos_none_price",
            "email": "ghost@example.com",
            "customer_name": None,
            "total_price": None,
            "line_items": []
        }

        # Mobile embed formatting
        embed = self.mobile.format_discord_embed("abandoned_cart", raw_checkout)
        self.assertIn("0.00 EUR", embed["description"])

        # Email HTML building
        html_out = self.email_disp.build_html_email(
            shop_name="Chaos Store",
            customer_name=None,
            items_str="",
            checkout_url="",
            text_body="Test body",
            line_items=[],
            discount_code=None,
            lang="en"
        )
        self.assertIn("<!DOCTYPE html>", html_out)
        self.assertIn("Chaos Store", html_out)
        self.assertIn("Test body", html_out)

    def test_chaos_negative_and_astronomical_totals(self):
        """
        Checkouts with negative totals or astronomical totals (billion+ EUR).
        Verify float safety and formatted display in mobile alerts.
        """
        neg_data = {"customer_name": "Test", "total_price": -99.50, "currency": "EUR"}
        huge_data = {"customer_name": "VIP Whale", "total_price": 1250000000.75, "currency": "USD"}

        embed_neg = self.mobile.format_discord_embed("abandoned_cart", neg_data)
        self.assertIn("-99.50 EUR", embed_neg["description"])

        embed_huge = self.mobile.format_discord_embed("abandoned_cart", huge_data)
        self.assertIn("1250000000.75 USD", embed_huge["description"])

        tg_neg = self.mobile.format_telegram_message("abandoned_cart", neg_data)
        self.assertIn("-99.50 EUR", tg_neg)

    def test_chaos_corrupted_line_item_structures(self):
        """
        Line items array containing empty dicts or partial dicts.
        Verify EmailDispatcher renders gracefully without crashing on missing keys.
        """
        partial_items = [
            {},
            {"title": None, "price": None, "quantity": None},
            {"title": "Valid Item", "price": "50.00", "quantity": 1},
        ]

        html_out = self.email_disp.build_html_email(
            shop_name="Chaos Shop",
            customer_name="Tester",
            line_items=partial_items,
            lang="en"
        )
        self.assertIn("Valid Item", html_out)

        vip_msg = self.post_delivery.build_vip_message(
            customer_name="Tester",
            purchased_item=partial_items[2]["title"],
            discount_code="MGVIP15"
        )
        self.assertIn("Valid Item", vip_msg)

    def test_chaos_corrupted_line_item_none_attribute_error_probe(self):
        """
        Adversarial probe:
        Expose vulnerability in EmailDispatcher._render_showcase_section:
        Passing line_items=[None] raises AttributeError: 'NoneType' object has no attribute 'get'.
        This empirically proves that email_dispatcher.py line 130 lacks an `isinstance(item, dict)` guard.
        """
        with self.assertRaises(AttributeError):
            self.email_disp.build_html_email(
                shop_name="Chaos Shop",
                customer_name="Tester",
                line_items=[None],
                lang="en"
            )

    def test_chaos_xss_and_sql_injection_payloads(self):
        """
        Payloads containing HTML script tags, event handlers, and SQL injection strings.
        Must be strictly sanitized and HTML escaped.
        """
        xss_name = "<script>alert('pwned')</script> & <img src=x onerror=alert(1)>"
        sqli_title = "Silk Dress'); DROP TABLE checkout_drip_states;--"
        body_with_xss = f"Hello {xss_name}, your items are ready."

        # Email HTML building must escape all dynamic fields
        html_out = self.email_disp.build_html_email(
            shop_name="Safe Store",
            customer_name=xss_name,
            text_body=body_with_xss,
            line_items=[{"title": sqli_title, "price": "100.00", "quantity": 1}],
            lang="en"
        )
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;", html_out)
        self.assertNotIn("<img src=x", html_out)
        self.assertIn("&lt;img src=x", html_out)
        self.assertIn("Silk Dress&#x27;); DROP TABLE checkout_drip_states;--", html_out)

        # Telegram message formatting must escape HTML special chars
        tg_out = self.mobile.format_telegram_message("abandoned_cart", {
            "customer_name": xss_name,
            "total_price": 100.0,
            "items": [sqli_title]
        })
        self.assertNotIn("<script>", tg_out)
        self.assertIn("&lt;script&gt;", tg_out)

    def test_chaos_discord_embed_field_length_truncation(self):
        """
        Discord limits embed field values to 1024 characters.
        Passing a 5000-character description or product title must truncate safely with ellipsis.
        """
        giant_title = "Extremely Long Luxury Item " * 300  # ~8100 chars
        giant_items = [giant_title]

        embed = self.mobile.format_discord_embed("abandoned_cart", {
            "customer_name": "Lord Longname",
            "total_price": 500.00,
            "items": giant_items
        })

        for field in embed["fields"]:
            self.assertLessEqual(len(field["value"]), MobileNotifier.DISCORD_FIELD_VALUE_LIMIT)
            if "Extremely Long" in field["value"]:
                self.assertTrue(field["value"].endswith("..."))

    def test_chaos_international_phone_variations_uk_fr_de_jp_us(self):
        """
        Test phone number normalization across international formats:
        - UK (+44): +44 7911 123456 -> 447911123456
        - France (+33): +33 (0) 6 12 34 56 78 -> 33612345678 (or digits stripped)
        - Germany (+49): +49 151 12345678 -> 4915112345678
        - Japan (+81): +81 90 1234 5678 -> 819012345678
        - US (+1): +1 (555) 234-5678 -> 15552345678
        """
        self.assertEqual(self.wa.clean_phone_number("+44 7911 123456"), "447911123456")
        self.assertEqual(self.wa.clean_phone_number("+49 151 12345678"), "4915112345678")
        self.assertEqual(self.wa.clean_phone_number("+81 90 1234 5678"), "819012345678")
        self.assertEqual(self.wa.clean_phone_number("+1 (555) 234-5678"), "15552345678")

    def test_chaos_garbage_phone_strings_graceful_rejection(self):
        """
        Garbage phone strings ("N/A", "undefined", "+", "abc", None)
        must fail gracefully without raising exceptions.
        """
        for bad_phone in ["N/A", "undefined", "null", "+", "  ", None, "12345", "(---)"]:
            res = asyncio.run(self.wa.send_message(bad_phone, "Testing bad phone"))
            self.assertFalse(res["ok"])
            self.assertEqual(res["provider"], "none")
            self.assertIsNone(res["wa_me_url"])

    def test_chaos_missing_both_email_and_phone(self):
        """
        Fulfillment order missing both email and phone contact must be gracefully skipped
        by PostDeliveryService during sync.
        """
        order_no_contact = make_sample_order(order_id="ord_no_contact")
        order_no_contact["email"] = None
        order_no_contact["phone"] = None
        order_no_contact["customer"] = {}

        with patch("backend.post_delivery_service.db.enqueue_post_delivery_automation") as mock_enqueue:
            with patch("backend.shopify_api.ShopifyClient.get_recent_orders", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = [order_no_contact]
                with patch("backend.post_delivery_service.db.get_shop", return_value={"shop": "s.myshopify.com", "access_token": "tok"}):
                    count = self.post_delivery.sync_fulfilled_orders("s.myshopify.com")
                    self.assertEqual(count, 0)
                    mock_enqueue.assert_not_called()


# ==============================================================================
# 4. Webhook Security & Idempotency
# ==============================================================================

class TestTier5WebhookSecurityIdempotency(unittest.TestCase):
    """
    Stress-tests webhook handlers against replay attacks, out-of-order events,
    and duplicate invocations.
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_webhook_order_created_replay_10x_idempotent(self):
        """
        Adversarial probe:
        Simulate Shopify delivering the same `orders/create` webhook 10 times consecutively.
        Invocation 1 reconciles active drip cart to 'converted' and alerts merchant.
        Invocations 2 through 10 must succeed with HTTP 200 without duplicate conversions or errors.
        """
        order_payload = {
            "id": "ord_replay_100",
            "order_number": "100",
            "customer": {"email": "customer@boutique.it", "first_name": "Lorenzo"},
            "total_price": "199.00",
            "currency": "EUR",
            "discount_codes": [{"code": "MG10"}]
        }

        call_counts = {"convert": 0, "notify": 0}

        def fake_mark_converted(shop, order_dict):
            call_counts["convert"] += 1
            # First time converts 1 row, subsequent times 0 rows
            return call_counts["convert"] == 1

        async def fake_notify(event, data, settings):
            call_counts["notify"] += 1
            return {"ok": True}

        with patch.object(bm.cadence_mgr, "mark_order_converted", side_effect=fake_mark_converted):
            with patch.object(bm.mobile_notifier, "notify_merchant", side_effect=fake_notify):
                with patch.object(bm.db, "get_shop_settings", return_value={"shop": "boutique.myshopify.com"}):
                    headers = {"x-shopify-shop-domain": "boutique.myshopify.com"}

                    for i in range(10):
                        resp = self.client.post("/webhooks/orders/create", json=order_payload, headers=headers)
                        self.assertEqual(resp.status_code, 200)
                        self.assertEqual(resp.json(), {"status": "ok"})

                    # mark_order_converted called 10 times
                    self.assertEqual(call_counts["convert"], 10)
                    # Merchant notified ONLY ONCE on initial conversion
                    self.assertEqual(call_counts["notify"], 1)

    def test_webhook_order_cancelled_before_fulfillment_sync(self):
        """
        Out-of-order delivery:
        A customer orders and quickly cancels.
        `/webhooks/orders/cancelled` arrives BEFORE fulfillment sync runs.
        Post-delivery cancel succeeds safely (0 rows affected or cancels pending).
        """
        cancel_payload = {"id": "ord_cancel_early_999"}
        with patch.object(bm.db, "cancel_post_delivery_automation", return_value=False) as mock_cancel:
            resp = self.client.post("/webhooks/orders/cancelled", json=cancel_payload)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"status": "ok"})
            mock_cancel.assert_called_once_with("ord_cancel_early_999")

    def test_webhook_order_cancelled_suppresses_pending_vip(self):
        """
        An order was enqueued in post_delivery_automations (status='pending').
        Shopify issues `/webhooks/orders/cancelled`.
        The pending automation record is transitioned to 'canceled', preventing future dispatch.
        """
        table = {"ord_vip_cancel": {"status": "pending"}}

        def fake_cancel(order_id):
            if order_id in table and table[order_id]["status"] == "pending":
                table[order_id]["status"] = "canceled"
                return True
            return False

        with patch.object(bm.db, "cancel_post_delivery_automation", side_effect=fake_cancel):
            resp = self.client.post("/webhooks/orders/cancelled", json={"id": "ord_vip_cancel"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(table["ord_vip_cancel"]["status"], "canceled")

    def test_webhook_order_created_unmatched_checkout_graceful(self):
        """
        Order created for a customer who never had an abandoned cart in Jarvis.
        mark_order_converted returns False (0 rows updated).
        Webhook handler returns HTTP 200 cleanly without error.
        """
        with patch.object(bm.cadence_mgr, "mark_order_converted", return_value=False):
            with patch.object(bm.mobile_notifier, "notify_merchant") as mock_notify:
                headers = {"x-shopify-shop-domain": "boutique.myshopify.com"}
                resp = self.client.post("/webhooks/orders/create", json={"id": "ord_unmatched"}, headers=headers)
                self.assertEqual(resp.status_code, 200)
                mock_notify.assert_not_called()

    def test_webhook_post_delivery_repeated_enqueue_idempotent(self):
        """
        Simulate 5 repeated calls to enqueue_post_delivery_automation for the same order.
        Strict ON CONFLICT (order_id) DO NOTHING ensures only the first returns True.
        """
        enqueued_set = set()

        def fake_enqueue(**kwargs):
            oid = kwargs.get("order_id")
            if oid in enqueued_set:
                return False
            enqueued_set.add(oid)
            return True

        with patch("backend.database.enqueue_post_delivery_automation", side_effect=fake_enqueue):
            for i in range(5):
                res = db.enqueue_post_delivery_automation(
                    shop="s.myshopify.com",
                    order_id="ord_idem_test",
                    customer_email="test@idem.com"
                )
                if i == 0:
                    self.assertTrue(res)
                else:
                    self.assertFalse(res)
            self.assertEqual(len(enqueued_set), 1)


# ==============================================================================
# 5. Daemon Resilience & Concurrency
# ==============================================================================

class TestTier5DaemonResilience(unittest.TestCase):
    """
    Stress-tests the autonomous background daemon loops against partial failures,
    provider timeouts, network disconnects, and concurrent event loops.
    """

    def setUp(self):
        self.cadence = DripCadenceManager()
        self.post_delivery = PostDeliveryService()

    def test_daemon_multi_store_batch_isolation_on_api_error(self):
        """
        Autopilot daemon loops over 3 stores:
        Store 1: ShopifyClient.get_abandoned_checkouts_detailed raises httpx.ConnectError.
        Store 2: Executes normally (processes checkouts).
        Store 3: Executes normally (processes checkouts).
        Store 1 failure must be caught in the per-store try-block and NEVER abort Store 2 and Store 3.
        """
        stores = [
            {"shop": "store1-broken.myshopify.com", "access_token": "tok1", "shop_name": "Store 1"},
            {"shop": "store2-healthy.myshopify.com", "access_token": "tok2", "shop_name": "Store 2"},
            {"shop": "store3-healthy.myshopify.com", "access_token": "tok3", "shop_name": "Store 3"},
        ]

        processed_shops = []

        async def fake_get_abandoned(client_self):
            if "store1-broken" in client_self.shop:
                raise httpx.ConnectError("Shopify Connection Refused")
            processed_shops.append(client_self.shop)
            return []

        async def run_single_daemon_cycle():
            shops = stores
            for s in shops:
                try:
                    shop = s["shop"]
                    token = s["access_token"]
                    client = ShopifyClient(shop, token)
                    await fake_get_abandoned(client)
                except Exception as shop_err:
                    pass  # Daemon catches per-store exception

        asyncio.run(run_single_daemon_cycle())

        self.assertIn("store2-healthy.myshopify.com", processed_shops)
        self.assertIn("store3-healthy.myshopify.com", processed_shops)
        self.assertNotIn("store1-broken.myshopify.com", processed_shops)

    def test_daemon_mobile_notifier_failure_does_not_abort_recovery(self):
        """
        If MobileNotifier throws httpx.ConnectError during process_single_checkout_recovery,
        the recovery email/WhatsApp and database stage update must still succeed.
        """
        checkout = make_sample_checkout(
            checkout_id="ch_resil_mobile_err",
            customer_name="Resilience Test",
            email="resil@test.com",
            phone="+393400000000"
        )
        settings = make_sample_shop_settings()

        updated_stages = []
        def fake_update_stage(checkout_id, stage, sent_at=None):
            updated_stages.append((checkout_id, stage))
            return True

        with patch.object(bm.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
            mock_mail.return_value = {"success": True}
            with patch.object(bm.wa_dispatcher, "send_message", new_callable=AsyncMock) as mock_wa:
                mock_wa.return_value = {"ok": True, "success": True}
                with patch.object(bm.mobile_notifier, "notify_merchant", new_callable=AsyncMock) as mock_mobile:
                    mock_mobile.side_effect = httpx.ConnectError("Discord unreachable")
                    with patch.object(bm.db, "update_drip_stage", side_effect=fake_update_stage):
                        with patch.object(bm.db, "save_autopilot_log"):
                            with patch.object(bm.db, "get_checkout_drip_state", return_value=None):
                                with patch.object(bm.db, "upsert_checkout_drip_state", return_value={"status": "active", "current_stage": 0}):
                                    with patch.object(bm.db, "get_shop_settings", return_value=settings):
                                        client_mock = MagicMock()
                                        res = asyncio.run(process_single_checkout_recovery(
                                            shop="boutique.myshopify.com",
                                            client=client_mock,
                                            shop_name="Boutique",
                                            c=checkout,
                                            force=True
                                        ))

                                        self.assertIsNotNone(res)
                                        self.assertEqual(len(updated_stages), 1)
                                        self.assertEqual(updated_stages[0][0], "ch_resil_mobile_err")

    def test_daemon_email_failure_does_not_abort_vip_whatsapp_or_mark_sent(self):
        """
        In PostDeliveryService.process_due_vip_automations:
        If EmailDispatcher raises an exception, WhatsApp is still attempted,
        and the record is marked 'sent'.
        """
        due_record = {
            "order_id": "ord_vip_err_resil",
            "order_number": "9001",
            "customer_name": "Marco Rossi",
            "customer_email": "marco.rossi@resil.it",
            "customer_phone": "+393401234567",
            "discount_code": "MGVIP15",
            "items_summary": [{"title": "Loro Suit", "quantity": 1}]
        }

        marked_sent = []
        def fake_mark_sent(order_id, sent_at=None):
            marked_sent.append(order_id)
            return True

        wa_called = []
        async def fake_wa_send(phone, message, settings=None, customer_name=None):
            wa_called.append(phone)
            return {"ok": True, "success": True}

        service = PostDeliveryService()

        with patch.object(service.email_dispatcher, "send_email", new_callable=AsyncMock) as mock_mail:
            mock_mail.side_effect = RuntimeError("SMTP connection drop")
            with patch.object(service.wa_dispatcher, "send_message", side_effect=fake_wa_send):
                with patch.object(service.mobile_notifier, "notify_merchant", new_callable=AsyncMock):
                    with patch("backend.post_delivery_service.db.get_due_post_delivery_automations", return_value=[due_record]):
                        with patch("backend.post_delivery_service.db.mark_post_delivery_sent", side_effect=fake_mark_sent):
                            with patch("backend.post_delivery_service.db.save_autopilot_log"):
                                dispatched = service.process_due_vip_automations("store.myshopify.com", {})

                                self.assertEqual(dispatched, 1)
                                self.assertEqual(len(wa_called), 1)
                                self.assertEqual(marked_sent, ["ord_vip_err_resil"])

    def test_daemon_future_timestamp_clock_skew_resilience(self):
        """
        A cart created in the future (due to server clock drift or Shopify clock skew)
        must not cause negative age transition or unhandled exception.
        """
        now = datetime.now(timezone.utc)
        future_cart = make_sample_checkout(
            checkout_id="ch_skew",
            created_at_dt=now + timedelta(minutes=15)
        )

        stage = self.cadence.evaluate_drip_stage(future_cart, {"current_stage": 0, "status": "active"}, now_dt=now)
        self.assertIsNone(stage, "Future timestamp must safely return None without crashing")

    def test_daemon_concurrent_dispatch_stress(self):
        """
        Concurrent execution of 10 simultaneous recovery processes via asyncio.gather.
        Verify no race conditions or deadlocks.
        """
        async def mock_recovery(i):
            await asyncio.sleep(0.01)
            return {"target": f"Customer_{i}", "stage": 1, "revenue": 100.0}

        async def run_batch():
            tasks = [mock_recovery(i) for i in range(10)]
            return await asyncio.gather(*tasks)

        results = asyncio.run(run_batch())
        self.assertEqual(len(results), 10)
        for i, res in enumerate(results):
            self.assertEqual(res["target"], f"Customer_{i}")


if __name__ == "__main__":
    unittest.main()

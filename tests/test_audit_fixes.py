"""
Regression tests for the November 2026 audit fixes:
SSRF guard, VIP expiry / delivery-based schedule / stored language, opt-out lift, OAuth nonce TTL,
admin-key brute-force brake, server-side billing test mode, webhook de-duplication, checkout locale,
per-checkout error isolation and SMTP TLS verification.
"""

try:
    from tests import _test_env  # noqa: F401  (isolated SQLite file per test run)
except ImportError:  # pragma: no cover
    import _test_env  # noqa: F401
import asyncio
import json
import os
import ssl
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

try:
    from tests.auth_helpers import AUTH_HEADERS, webhook_headers  # noqa: E402
except ImportError:  # pragma: no cover
    from auth_helpers import AUTH_HEADERS, webhook_headers  # noqa: E402

import auth_guard  # noqa: E402
import database as db  # noqa: E402
import main  # noqa: E402
import net_guard  # noqa: E402
import post_delivery_service as pds  # noqa: E402
from email_dispatcher import EmailDispatcher  # noqa: E402
from shopify_api import detect_customer_language_and_country  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

SHOP = "maisongrozavu.myshopify.com"
NOON = datetime(2026, 11, 3, 11, 0, tzinfo=timezone.utc)  # 12:00 Madrid


def uid() -> str:
    return uuid.uuid4().hex[:10]


class TestNetGuard(unittest.TestCase):
    def test_legacy_ipv4_spellings_and_local_names_are_refused(self):
        for url in ("https://127.1/x", "https://0x7f.0.0.1/x", "https://2130706433/x", "https://127.0.0.1/x",
                    "https://[::1]/x", "https://169.254.169.254/latest", "https://10.0.0.5/hook",
                    "https://localhost/x", "https://printer.local/x", "https://db.internal/x",
                    "http://example.com/x", "https://user:pw@example.com/x"):
            self.assertFalse(net_guard.is_public_https_url(url), url)
            self.assertFalse(main._safe_public_url(url), url)

    def test_public_https_urls_are_allowed(self):
        for url in ("https://discord.com/api/webhooks/1/abc", "https://hooks.example.com/x", "https://8.8.8.8/x"):
            self.assertTrue(net_guard.is_public_https_url(url), url)

    def test_name_resolving_to_a_private_address_is_refused_at_send_time(self):
        fake = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch("net_guard.socket.getaddrinfo", return_value=fake):
            self.assertFalse(net_guard.url_resolves_public("https://127.0.0.1.nip.io/x"))
        public = [(2, 1, 6, "", ("162.159.135.232", 443))]
        with patch("net_guard.socket.getaddrinfo", return_value=public):
            self.assertTrue(net_guard.url_resolves_public("https://discord.com/api/webhooks/1/a"))

    def test_discord_and_webhook_senders_refuse_private_targets(self):
        from mobile_notifier import MobileNotifier
        from whatsapp_dispatcher import WhatsAppDispatcher
        fake = [(2, 1, 6, "", ("10.1.2.3", 443))]
        with patch("net_guard.socket.getaddrinfo", return_value=fake), \
                patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
            dc = asyncio.run(MobileNotifier().send_discord_notification("https://evil.example.com/h", {"title": "t"}))
            wa = asyncio.run(WhatsAppDispatcher()._dispatch_webhook("34600111222", "hi", "https://evil.example.com/h"))
        post.assert_not_called()
        self.assertFalse(dc["ok"])
        self.assertFalse(wa["success"])

    def test_smtp_verifies_certificates_and_refuses_private_hosts(self):
        cfg = {"host": "smtp.example-mail.com", "port": 587, "user": "u", "password": "p"}
        server = MagicMock()
        with patch("email_dispatcher.smtplib.SMTP", return_value=server):
            EmailDispatcher._smtp_send_blocking(cfg, "a@b.com", "c@d.com", "msg")
        ctx = server.starttls.call_args.kwargs["context"]
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        with self.assertRaises(ValueError):
            EmailDispatcher._smtp_send_blocking(dict(cfg, host="127.0.0.1"), "a@b.com", "c@d.com", "msg")


class TestVipSchedule(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.svc = pds.PostDeliveryService()
        self.sent = []

        async def fake_send(**kw):
            self.sent.append(kw["to_email"])
            return {"success": True, "provider": "fake"}
        self.svc.email_dispatcher.send_email = fake_send

    def _queue(self, email, scheduled_for, lang=None):
        order_id = uid()
        db.record_marketing_consent(SHOP, email=email, accepts_marketing=True)
        db.enqueue_post_delivery_automation(shop=SHOP, order_id=order_id, order_number="1001", customer_email=email,
                                            customer_name="Ana", fulfilled_at=scheduled_for - timedelta(days=5),
                                            scheduled_for=scheduled_for, items_summary=[{"title": "Hoodie"}],
                                            lang=lang)
        return order_id

    def test_far_too_late_thank_you_expires_instead_of_sending(self):
        order_id = self._queue(f"late-{uid()}@x.com", NOON - timedelta(days=40))
        with patch("post_delivery_service.db.get_due_post_delivery_automations",
                   return_value=[db.get_post_delivery_automation(order_id)]):
            sent = self.svc.process_due_vip_automations(SHOP, {"shop": SHOP}, now_dt=NOON)
        self.assertEqual(sent, 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(db.get_post_delivery_automation(order_id)["status"], "expired")

    def test_recent_thank_you_is_sent_in_the_stored_language(self):
        email = f"ok-{uid()}@x.com"
        order_id = self._queue(email, NOON - timedelta(days=1), lang="es")
        captured = {}

        async def fake_send(**kw):
            captured.update(kw)
            return {"success": True}
        self.svc.email_dispatcher.send_email = fake_send
        with patch("post_delivery_service.db.get_due_post_delivery_automations",
                   return_value=[db.get_post_delivery_automation(order_id)]):
            sent = self.svc.process_due_vip_automations(SHOP, {"shop": SHOP}, now_dt=NOON)
        self.assertEqual(sent, 1)
        self.assertIn("Gracias", captured["body_text"])

    def test_schedule_follows_carrier_tracking(self):
        f_at = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
        cs = pds.PostDeliveryService.compute_schedule
        self.assertEqual(cs([{"created_at": f_at.isoformat()}], f_at), f_at + timedelta(days=5))
        self.assertEqual(cs([{"shipment_status": "in_transit"}], f_at), f_at + timedelta(days=14))
        delivered = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(cs([{"shipment_status": "delivered", "updated_at": delivered.isoformat()}], f_at),
                         delivered + timedelta(days=2))
        # one parcel delivered, another still travelling -> keep waiting
        self.assertEqual(cs([{"shipment_status": "delivered", "updated_at": delivered.isoformat()},
                             {"shipment_status": "in_transit"}], f_at), f_at + timedelta(days=14))

    def test_sync_moves_a_pending_thank_you_when_delivery_is_reported(self):
        order_id = str(int(uuid.uuid4().int % 10**12))
        f_at = datetime.now(timezone.utc) - timedelta(days=2)
        order = {"id": order_id, "order_number": 1001, "email": f"d-{uid()}@x.com", "customer": {"first_name": "Ana"},
                 "fulfillments": [{"status": "success", "created_at": f_at.isoformat(), "shipment_status": "in_transit"}],
                 "line_items": [{"title": "Hoodie"}], "customer_locale": "fr-FR"}
        db.upsert_shop(SHOP, "shpat_0123456789abcdef0123456789abcd", "Grozavu")
        fake = MagicMock()
        fake.get_recent_orders = AsyncMock(return_value=[order])
        with patch("post_delivery_service.ShopifyClient", return_value=fake):
            self.svc.sync_fulfilled_orders(SHOP, 14)
            row = db.get_post_delivery_automation(order_id)
            self.assertEqual(row["lang"], "fr")
            first = pds.PostDeliveryService.parse_datetime(row["scheduled_for"])
            self.assertAlmostEqual((first - f_at).total_seconds(), 14 * 86400, delta=5)
            delivered = f_at + timedelta(days=1)
            order["fulfillments"][0].update(shipment_status="delivered", updated_at=delivered.isoformat())
            self.svc.sync_fulfilled_orders(SHOP, 14)
        moved = pds.PostDeliveryService.parse_datetime(db.get_post_delivery_automation(order_id)["scheduled_for"])
        self.assertAlmostEqual((moved - delivered).total_seconds(), 2 * 86400, delta=5)

    def test_mark_sent_never_matches_another_rows_serial_id(self):
        a = self._queue(f"a-{uid()}@x.com", NOON)
        row_a = db.get_post_delivery_automation(a)
        self.assertFalse(db.mark_post_delivery_sent(str(row_a["id"])))  # serial id is not an order id
        self.assertEqual(db.get_post_delivery_automation(a)["status"], "pending")
        self.assertTrue(db.mark_post_delivery_sent(a))


class TestOptOutLift(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.client = TestClient(main.app, headers=AUTH_HEADERS)

    def test_lift_returns_to_unknown_never_granted(self):
        email = f"back-{uid()}@x.com"
        db.record_marketing_consent(SHOP, email=email, accepts_marketing=True)
        db.record_opt_out(SHOP, email=email)
        self.assertEqual(db.get_consent_status(SHOP, email=email, channel="email"), db.CONSENT_OPTED_OUT)
        r = self.client.post("/api/compliance/lift-opt-out", json={"shop": SHOP, "email": email})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["changed"])
        self.assertEqual(db.get_consent_status(SHOP, email=email, channel="email"), db.CONSENT_UNKNOWN)
        db.record_marketing_consent(SHOP, email=email, accepts_marketing=True, source="checkout")
        self.assertEqual(db.get_consent_status(SHOP, email=email, channel="email"), db.CONSENT_GRANTED)

    def test_lift_needs_auth_and_an_identity(self):
        self.assertEqual(TestClient(main.app).post("/api/compliance/lift-opt-out", json={"email": "a@b.com"}).status_code, 401)
        self.assertEqual(self.client.post("/api/compliance/lift-opt-out", json={"shop": SHOP}).status_code, 400)

    def test_shopify_denial_is_not_touched_by_a_lift(self):
        email = f"deny-{uid()}@x.com"
        db.record_marketing_consent(SHOP, email=email, accepts_marketing=False)
        self.assertFalse(db.lift_opt_out(SHOP, email=email))
        self.assertEqual(db.get_consent_status(SHOP, email=email, channel="email"), db.CONSENT_DENIED)


class TestNonceTtl(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_fresh_nonce_works_once(self):
        shop = f"n{uid()}.myshopify.com"
        db.store_nonce_fresh(shop, "abc")
        self.assertTrue(db.verify_and_delete_nonce(shop, "abc"))
        self.assertFalse(db.verify_and_delete_nonce(shop, "abc"))

    def test_expired_or_non_ascii_nonce_is_rejected(self):
        shop = f"n{uid()}.myshopify.com"
        db.store_nonce(shop, "abc")
        self.assertFalse(db.verify_and_delete_nonce(shop, "ăîș"))
        db.store_nonce(shop, "abc")
        old = datetime.now(timezone.utc) + timedelta(minutes=db.NONCE_TTL_MINUTES + 5)
        with patch("database._utc_naive", side_effect=lambda dt=None: (dt or old).astimezone(timezone.utc).replace(tzinfo=None)):
            self.assertFalse(db.verify_and_delete_nonce(shop, "abc"))


class TestAdminKeyBrake(unittest.TestCase):
    def tearDown(self):
        auth_guard._admin_key_failures.clear()

    def test_many_wrong_keys_pause_admin_key_logins(self):
        client = TestClient(main.app)
        auth_guard._admin_key_failures.clear()
        for _ in range(auth_guard.ADMIN_KEY_MAX_FAILURES):
            self.assertEqual(client.get("/api/snapshot", headers={"X-Jarvis-Key": "wrong-key-wrong-key"}).status_code, 401)
        self.assertEqual(client.get("/api/snapshot", headers={"X-Jarvis-Key": "wrong-key-wrong-key"}).status_code, 429)
        self.assertEqual(client.get("/api/snapshot", headers=AUTH_HEADERS).status_code, 429)
        auth_guard._admin_key_failures.clear()
        self.assertEqual(client.get("/api/snapshot", headers=AUTH_HEADERS).status_code, 200)


class TestBillingMode(unittest.TestCase):
    def setUp(self):
        db.init_db()
        db.upsert_shop(SHOP, "shpat_0123456789abcdef0123456789abcd", "Grozavu")
        self.client = TestClient(main.app, headers=AUTH_HEADERS)

    def test_client_cannot_choose_test_or_live(self):
        fake = MagicMock()
        fake.create_app_subscription = AsyncMock(return_value="https://admin.shopify.com/confirm")
        with patch.object(main, "ShopifyClient", return_value=fake), patch.dict(os.environ, {"JARVIS_BILLING_TEST": "0"}):
            self.client.post("/api/billing/create", json={"shop": SHOP, "test": True})
        self.assertFalse(fake.create_app_subscription.call_args.kwargs["test"])

    def test_live_mode_ignores_free_test_subscriptions(self):
        fake = MagicMock()
        fake.get_active_subscriptions = AsyncMock(return_value=[{"status": "ACTIVE", "test": True}])
        with patch.object(main, "ShopifyClient", return_value=fake), patch.dict(os.environ, {"JARVIS_BILLING_TEST": "0"}):
            r = self.client.get(f"/api/billing/callback?shop={SHOP}")
        self.assertIn("nu a putut fi confirmat", r.text)


class TestWebhookDedupe(unittest.TestCase):
    def test_same_webhook_id_is_processed_once(self):
        client = TestClient(main.app)
        body = json.dumps({"id": 987654321, "email": "x@y.com"}).encode()
        headers = dict(webhook_headers(body, shop=SHOP), **{"X-Shopify-Webhook-Id": f"wh-{uid()}"})
        with patch.object(main, "_reconcile", return_value=False) as rec:
            self.assertEqual(client.post("/webhooks/orders/create", content=body, headers=headers).status_code, 200)
            self.assertEqual(client.post("/webhooks/orders/create", content=body, headers=headers).status_code, 200)
        self.assertEqual(rec.call_count, 1)


class TestLanguageFromCheckoutLocale(unittest.TestCase):
    def test_locale_beats_name_and_country_guesses(self):
        self.assertEqual(detect_customer_language_and_country("Marco Rossi", "m@x.com", "", "CH", "", locale="fr-CH")["lang"], "fr")
        self.assertEqual(detect_customer_language_and_country("Marco Rossi", "m@x.com", "", "", "")["lang"], "it")
        self.assertEqual(detect_customer_language_and_country("", "", "", "ES", "", locale="xx")["lang"], "es")


class TestCheckoutIsolation(unittest.TestCase):
    def test_one_failing_checkout_does_not_stop_the_others(self):
        calls = []

        async def flaky(shop, client, shop_name, c, force=False, skip_log=None):
            calls.append(c["id"])
            if c["id"] == "1":
                raise RuntimeError("db hiccup")
            return {"status": "sent"}
        fake = MagicMock()
        fake.get_recent_orders = AsyncMock(return_value=[])
        fake.get_abandoned_checkouts_detailed = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])
        with patch.object(main, "ShopifyClient", return_value=fake), \
                patch.object(main, "process_single_checkout_recovery", side_effect=flaky), \
                patch.object(main.post_delivery_service, "sync_fulfilled_orders", return_value=0), \
                patch.object(main.post_delivery_service, "process_due_vip_automations", return_value=0):
            res = asyncio.run(main.run_shop_cycle({"shop": SHOP, "access_token": "shpat_0123456789abcdef0123456789abcd"}))
        self.assertEqual(calls, ["1", "2"])
        self.assertEqual(res["sent"], 1)
        self.assertTrue(any("db hiccup" in e for e in res["errors"]))


class TestSecurityHeaders(unittest.TestCase):
    def test_basic_hardening_headers(self):
        r = TestClient(main.app).get("/health")
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("max-age", r.headers.get("strict-transport-security", ""))


class TestHealthDoesNotWakeTheDatabase(unittest.TestCase):
    def test_repeated_health_pings_hit_the_db_at_most_once_per_window(self):
        client = TestClient(main.app)
        main._OAUTH_MODE_CACHE.update(at=0.0, oauth=False)
        with patch.dict(main.SHOPIFY_CONNECTION, {"mode": "none"}), \
                patch.object(main.db, "get_shop", return_value={"access_token": "shpat_0123456789abcdef0123456789abcd"}) as get_shop:
            for _ in range(10):
                self.assertEqual(client.get("/health").json()["shopify_connection"], "oauth")
        self.assertEqual(get_shop.call_count, 1)
        main._OAUTH_MODE_CACHE.update(at=0.0, oauth=False)


if __name__ == "__main__":
    unittest.main()

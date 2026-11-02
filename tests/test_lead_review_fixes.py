"""Regression tests for the issues found by the independent final review."""

try:
    from tests import _test_env  # noqa: F401  (isolated SQLite file per test run)
except ImportError:  # pragma: no cover
    import _test_env  # noqa: F401
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from tests.auth_helpers import AUTH_HEADERS, webhook_headers  # noqa: E402
except ImportError:
    from auth_helpers import AUTH_HEADERS, webhook_headers  # noqa: E402

import database as db  # noqa: E402
import main  # noqa: E402
from ai_advisor import AIAdvisor, validate_recovery_copy  # noqa: E402
from whatsapp_dispatcher import WhatsAppDispatcher  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

URL = "https://maisongrozavu.com/checkouts/ac/abc/recover?key=SECRET123"
SHOP = "maisongrozavu.myshopify.com"


class TestAICustomerCopyGuard(unittest.IsolatedAsyncioTestCase):
    def good(self, code="MG10"):
        return {"subject": "Your Grozavu cart", "body": f"Hi Ana, finish here: {URL} Use {code} at checkout.",
                "whatsapp_message": f"Hi Ana! Your cart: {URL} Code {code}"}

    def test_validator_accepts_clean_copy(self):
        self.assertIsNone(validate_recovery_copy(self.good(), URL, "MG10"))

    def test_validator_rejects_false_or_unsafe_copy(self):
        cases = {
            "reserved": dict(self.good(), body=f"Your items are reserved for you: {URL} MG10"),
            "unisex": dict(self.good(), body=f"Our unisex hoodie: {URL} MG10"),
            "foreign link": dict(self.good(), body=f"Go to https://evil.example/x {URL} MG10"),
            "other code": dict(self.good(), body=f"Use SPECIAL25 now {URL} MG10"),
            "missing link": dict(self.good(), whatsapp_message="Code MG10, come back!"),
            "placeholder": dict(self.good(), body=f"Hi {{{{NAME}}}} {URL} MG10"),
            "STOP": dict(self.good(), whatsapp_message=f"{URL} MG10 Reply STOP to opt out"),
        }
        for name, copy in cases.items():
            self.assertIsNotNone(validate_recovery_copy(copy, URL, "MG10"), name)
        no_code = {"subject": "Cart", "body": f"Here: {URL} 10% off", "whatsapp_message": URL}
        self.assertIsNotNone(validate_recovery_copy(no_code, URL, None))

    async def test_gemini_never_sees_name_or_checkout_link_and_bad_copy_falls_back(self):
        ai = AIAdvisor()
        sent_prompts = []

        async def fake_gemini(prompt, **kwargs):
            sent_prompts.append(prompt)
            return json.dumps({"subject": "Your cart is reserved!",
                               "body": "Hi {{NAME}}, items reserved: {{CHECKOUT_URL}} MG10",
                               "whatsapp_message": "{{CHECKOUT_URL}} MG10"})

        checkout = {"customer_name": "Ana Lopez", "checkout_url": URL, "items": ["Boxy Tee"], "detected_country": "ES"}
        with patch.object(ai, "_call_gemini", side_effect=fake_gemini):
            out = await ai.generate_autonomous_recovery("Grozavu", checkout, lang="es", discount_code="MG10")
        self.assertTrue(sent_prompts)
        self.assertNotIn("Ana", sent_prompts[0])
        self.assertNotIn("SECRET123", sent_prompts[0])
        self.assertNotEqual(out.get("source"), "gemini")  # "reserved" -> safe template instead
        self.assertIn(URL, out["body"])
        self.assertNotIn("reserv", out["body"].lower())

    async def test_good_gemini_copy_gets_real_values_filled_in(self):
        ai = AIAdvisor()

        async def fake_gemini(prompt, **kwargs):
            return json.dumps({"subject": "Tu carrito Grozavu",
                               "body": "Hola {{NAME}}, termina aquí: {{CHECKOUT_URL}} con MG10",
                               "whatsapp_message": "¡Hola {{NAME}}! {{CHECKOUT_URL}} MG10"})

        checkout = {"customer_name": "Ana", "checkout_url": URL, "items": ["Boxy Tee"]}
        with patch.object(ai, "_call_gemini", side_effect=fake_gemini):
            out = await ai.generate_autonomous_recovery("Grozavu", checkout, lang="es", discount_code="MG10")
        self.assertEqual(out.get("source"), "gemini")
        self.assertIn("Hola Ana", out["body"])
        self.assertIn(URL, out["whatsapp_message"])


class TestRefundCancelsPendingVip(unittest.TestCase):
    def test_refunded_order_cancels_pending_vip(self):
        import post_delivery_service as pds
        svc = pds.PostDeliveryService()
        order = {"id": 555, "financial_status": "refunded", "fulfillments": [{"created_at": "2026-10-20T10:00:00Z"}]}
        fake_client = MagicMock()
        fake_client.get_recent_orders = AsyncMock(return_value=[order])
        with patch.object(pds, "ShopifyClient", return_value=fake_client), \
                patch.object(pds.db, "get_shop", return_value={"shop": SHOP, "access_token": "shpat_0123456789abcdef"}), \
                patch.object(pds.db, "mark_post_delivery_status", return_value=True) as mark, \
                patch.object(pds.db, "enqueue_post_delivery_automation") as enqueue:
            count = svc.sync_fulfilled_orders(SHOP)
        self.assertEqual(count, 0)
        enqueue.assert_not_called()
        mark.assert_called_once_with("555", "canceled")


class TestWhatsAppEnvCredentials(unittest.IsolatedAsyncioTestCase):
    async def test_empty_stored_value_does_not_hide_env_credentials(self):
        wa = WhatsAppDispatcher()
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"messages": [{"id": "wamid.1"}]}
        env = {"WHATSAPP_PROVIDER": "meta", "WHATSAPP_API_TOKEN": "EAAenv", "WHATSAPP_PHONE_NUMBER_ID": "123"}
        with patch.dict(os.environ, env), \
                patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok) as post:
            res = await wa.send_message("+34600111222", "Test",
                                        settings={"whatsapp_provider": "", "whatsapp_api_token": "",
                                                  "whatsapp_phone_number_id": ""},
                                        message_type="transactional")
        self.assertTrue(res.get("success"), res)
        self.assertIn("Bearer EAAenv", str(post.call_args))


class TestMainReviewFixes(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.client = TestClient(main.app, headers=AUTH_HEADERS)

    def test_webhook_urls_must_be_public_https(self):
        for bad in ("http://169.254.169.254/latest", "https://localhost/x", "https://10.0.0.5/hook",
                    "https://127.0.0.1/hook", "file:///etc/passwd"):
            r = self.client.post("/api/settings/notifications", json={"shop": SHOP, "discord_webhook_url": bad})
            self.assertEqual(r.status_code, 400, bad)
        r = self.client.post("/api/settings/notifications",
                             json={"shop": SHOP, "discord_webhook_url": "https://discord.com/api/webhooks/1/abc"})
        self.assertEqual(r.status_code, 200)

    def test_whatsapp_test_ignores_custom_text(self):
        with patch.object(main.wa_dispatcher, "send_message", new_callable=AsyncMock,
                          return_value={"success": True}) as send, \
                patch.dict(os.environ, {"MERCHANT_NOTIFY_PHONE": "+34 600 000 000"}):
            self.client.post("/api/whatsapp/test", json={"shop": SHOP, "to_phone": "+34600000000",
                                                         "message": "Buy crypto now http://scam.example"})
        self.assertNotIn("scam", send.call_args.kwargs["message"])
        self.assertEqual(send.call_args.kwargs["message_type"], "transactional")

    def test_whatsapp_test_only_reaches_the_merchant_phone(self):
        with patch.object(main.wa_dispatcher, "send_message", new_callable=AsyncMock,
                          return_value={"success": True}) as send, \
                patch.dict(os.environ, {"MERCHANT_NOTIFY_PHONE": "+34600000000"}):
            r = self.client.post("/api/whatsapp/test", json={"shop": SHOP, "to_phone": "+34611222333"})
        self.assertEqual(r.status_code, 403)
        send.assert_not_called()

    def test_whatsapp_test_refuses_an_opted_out_number(self):
        db.record_opt_out(SHOP, phone="+34600999888")
        with patch.object(main.wa_dispatcher, "send_message", new_callable=AsyncMock,
                          return_value={"success": True}) as send, \
                patch.dict(os.environ, {"MERCHANT_NOTIFY_PHONE": "+34600999888"}):
            r = self.client.post("/api/whatsapp/test", json={"shop": SHOP, "to_phone": "+34600999888"})
        self.assertEqual(r.status_code, 403)
        send.assert_not_called()

    def test_gdpr_redact_uses_signed_shop_domain(self):
        body = json.dumps({"shop_domain": SHOP, "customer": {"email": "a@b.com"}, "orders_to_redact": [1]}).encode()
        headers = webhook_headers(body, shop="someone-else.myshopify.com")
        with patch.object(main.db, "redact_customer", return_value={}) as red:
            r = self.client.post("/webhooks/customers/redact", content=body, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(red.call_args.args[0], SHOP)

    def test_health_reports_real_daemon_state(self):
        data = self.client.get("/health").json()
        self.assertFalse(data["autopilot_running"])  # disabled in tests, so it must not claim it runs

    def test_head_requests_from_uptime_monitors_succeed(self):
        for path in ("/health", "/"):
            r = TestClient(main.app).head(path)
            self.assertEqual(r.status_code, 200, path)


class TestBrandedEmailAndSample(unittest.TestCase):
    LOGO = "https://cdn.shopify.com/s/files/1/0000/files/grozavu-hare-white.png"

    def test_logo_only_from_https_env(self):
        from email_dispatcher import EmailDispatcher
        with patch.dict(os.environ, {"EMAIL_LOGO_URL": self.LOGO}):
            html_out = EmailDispatcher.build_html_email(shop_name="Grozavu", text_body="Hola", lang="es")
        self.assertIn(f'src="{self.LOGO}"', html_out)
        for bad in ("", "http://insecure.example/logo.png", "javascript:alert(1)"):
            with patch.dict(os.environ, {"EMAIL_LOGO_URL": bad}):
                html_out = EmailDispatcher.build_html_email(shop_name="Grozavu", text_body="Hola", lang="es")
            self.assertNotIn('alt="Grozavu" width="96"', html_out, bad)

    def test_sample_cart_email_goes_only_to_merchant_with_real_products(self):
        products = [
            {"title": "No image", "variants": [{"price": "10.00", "title": "M"}], "images": []},
            {"title": "Boxy Tee GROZAVU", "image": {"src": "https://cdn.shopify.com/a.jpg"},
             "variants": [{"price": "39.00", "title": "Black / M"}]},
            {"title": "Crewneck SS26", "images": [{"src": "https://cdn.shopify.com/b.jpg"}],
             "variants": [{"price": "79.00", "title": "Default Title"}]},
        ]
        self.assertEqual([i["title"] for i in main.sample_line_items(products)], ["Boxy Tee GROZAVU", "Crewneck SS26"])
        db.init_db()
        db.upsert_shop(SHOP, "shpat_0123456789abcdef0123456789abcd", "Grozavu")
        client = TestClient(main.app, headers=AUTH_HEADERS)
        with patch.object(main, "load_feed_products", new_callable=AsyncMock, return_value=(products, None)), \
                patch.object(main.email_dispatcher, "send_email", new_callable=AsyncMock,
                             return_value={"success": True, "provider": "resend"}) as send, \
                patch.dict(os.environ, {"MERCHANT_NOTIFY_EMAIL": "Owner@Example.org"}):
            r = client.post("/api/email/test", json={"shop": SHOP, "to_email": "owner@example.org"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["sample_products"], 2)
        kw = send.call_args.kwargs
        self.assertEqual(kw["to_email"], "owner@example.org")
        self.assertTrue(kw["subject"].startswith("[TEST]"))
        self.assertTrue(kw["is_internal"])
        self.assertIn("Boxy Tee GROZAVU", kw["body_html"])
        self.assertIn("MG10", kw["body_html"])

    def test_basic_test_email_still_available(self):
        db.init_db()
        db.upsert_shop(SHOP, "shpat_0123456789abcdef0123456789abcd", "Grozavu")
        client = TestClient(main.app, headers=AUTH_HEADERS)
        with patch.object(main.email_dispatcher, "send_email", new_callable=AsyncMock,
                          return_value={"success": True}) as send, \
                patch.dict(os.environ, {"MERCHANT_NOTIFY_EMAIL": "owner@example.org"}):
            client.post("/api/email/test", json={"shop": SHOP, "to_email": "owner@example.org", "kind": "basic"})
        self.assertIn("[Jarvis Test]", send.call_args.kwargs["subject"])

    def test_test_email_never_goes_to_a_customer(self):
        db.init_db()
        client = TestClient(main.app, headers=AUTH_HEADERS)
        with patch.object(main.email_dispatcher, "send_email", new_callable=AsyncMock,
                          return_value={"success": True}) as send, \
                patch.dict(os.environ, {"MERCHANT_NOTIFY_EMAIL": "owner@example.org"}):
            r = client.post("/api/email/test", json={"shop": SHOP, "to_email": "random.customer@gmail.com"})
            own_domain = client.post("/api/email/test", json={"shop": SHOP, "to_email": "team@maisongrozavu.com",
                                                              "kind": "basic"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(own_domain.status_code, 200)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["to_email"], "team@maisongrozavu.com")


class TestAutopilotInterval(unittest.TestCase):
    """Neon free = 100 CU-h/month and 5-minute idle suspend: a 5-minute loop would never let it sleep."""

    def test_interval_defaults_and_override(self):
        with patch.dict(os.environ, {"JARVIS_AUTOPILOT_MINUTES": ""}):
            with patch.object(main.db, "DATABASE_URL",
                              "postgresql://u:p@ep-x-pooler.c-4.us-west-2.aws.neon.tech/neondb?sslmode=require"):
                self.assertEqual(main.autopilot_interval_minutes(), 15)
            with patch.object(main.db, "DATABASE_URL", "postgresql://u:p@db.example.com/x"):
                self.assertEqual(main.autopilot_interval_minutes(), 5)
            with patch.object(main.db, "DATABASE_URL", ""):
                self.assertEqual(main.autopilot_interval_minutes(), 5)
        for raw, expected in (("10", 10), ("0", 1), ("500", 60), ("abc", 5)):
            with patch.dict(os.environ, {"JARVIS_AUTOPILOT_MINUTES": raw}), patch.object(main.db, "DATABASE_URL", ""):
                self.assertEqual(main.autopilot_interval_minutes(), expected, raw)


class TestEphemeralDatabaseGuard(unittest.TestCase):
    """On Render without DATABASE_URL, unsubscribes would be wiped on restart -> no marketing."""

    def test_marketing_waits_for_postgres_on_render(self):
        from datetime import datetime, timezone
        import compliance_guard as cg
        noon_madrid = datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"RENDER": "true", "JARVIS_ALLOW_EPHEMERAL_DB": ""}), \
                patch.object(cg.db, "DATABASE_URL", ""), patch.object(cg.db, "USING_SQLITE", True):
            ok, reason = cg.can_dispatch_to_customer(SHOP, email="ana@test.es", channel="email", now_dt=noon_madrid)
            self.assertFalse(ok)
            self.assertTrue(reason.startswith(cg.REASON_EPHEMERAL_DB), reason)
            self.assertTrue(cg.is_transient_block(reason))  # VIP is held, not suppressed forever
            ok, _ = cg.can_dispatch_to_customer(SHOP, email="ana@test.es", channel="email", now_dt=noon_madrid,
                                                message_type="transactional")
            self.assertTrue(ok)
            self.assertIsNotNone(TestClient(main.app).get("/health").json()["marketing_paused_reason"])
        with patch.dict(os.environ, {"RENDER": "true"}), patch.object(cg.db, "USING_SQLITE", False):
            self.assertFalse(cg.ephemeral_db_blocks_marketing())
        with patch.dict(os.environ, {"RENDER": "true", "JARVIS_ALLOW_EPHEMERAL_DB": "1"}), \
                patch.object(cg.db, "USING_SQLITE", True):
            self.assertFalse(cg.ephemeral_db_blocks_marketing())

    def test_local_runs_are_not_blocked(self):
        import compliance_guard as cg
        env = {k: v for k, v in os.environ.items() if k not in ("RENDER", "RENDER_EXTERNAL_URL")}
        with patch.dict(os.environ, env, clear=True), patch.object(cg.db, "USING_SQLITE", True):
            self.assertFalse(cg.ephemeral_db_blocks_marketing())


if __name__ == "__main__":
    unittest.main()

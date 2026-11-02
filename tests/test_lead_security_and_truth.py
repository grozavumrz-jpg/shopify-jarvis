"""
Regression tests for the security / truthfulness fixes in main.py, auth_guard.py
and google_merchant_feed.py. No real network calls: ShopifyClient is mocked.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
for p in (PROJECT_ROOT, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

ADMIN_KEY = "test-admin-key-0123456789"
API_KEY = "test_api_key_123"
API_SECRET = "test_api_secret_456"
os.environ["JARVIS_ADMIN_KEY"] = ADMIN_KEY
os.environ["SHOPIFY_API_KEY"] = API_KEY
os.environ["SHOPIFY_API_SECRET"] = API_SECRET
os.environ["JARVIS_DISABLE_DAEMON"] = "1"
os.environ.setdefault("SHOPIFY_AUTH_MODE", "oauth")

import database as db  # noqa: E402
import main  # noqa: E402
from auth_guard import normalize_shop, verify_session_token, verify_webhook_hmac  # noqa: E402
from google_merchant_feed import build_feed_items, build_google_merchant_xml, validate_google_merchant_feed  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

SHOP = "maisongrozavu.myshopify.com"
AUTH = {"X-Jarvis-Key": ADMIN_KEY}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_session_token(shop=SHOP, aud=API_KEY, secret=API_SECRET, exp_offset=60, nbf_offset=-5):
    now = int(time.time())
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({
        "iss": f"https://{shop}/admin", "dest": f"https://{shop}", "aud": aud, "sub": "1",
        "exp": now + exp_offset, "nbf": now + nbf_offset, "iat": now, "jti": "x", "sid": "y",
    }).encode())
    sig = b64url(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def sample_products():
    return [{
        "id": 111, "title": "Grozavu SS26 Crewneck", "handle": "grozavu-ss26-crewneck",
        "body_html": "<p>Heavyweight 380 g/m² fleece crewneck &amp; embroidered logo.</p>",
        "product_type": "Crewneck", "vendor": "Grozavu", "tags": "streetwear", "status": "active",
        "published_at": "2026-09-01T10:00:00Z",
        "options": [{"name": "Color", "position": 1}, {"name": "Size", "position": 2}],
        "images": [{"id": 9, "src": "https://cdn.shopify.com/s/files/crew-black.jpg"},
                   {"id": 10, "src": "https://cdn.shopify.com/s/files/crew-back.jpg"}],
        "variants": [
            {"id": 1, "price": "89.00", "compare_at_price": None, "option1": "Black", "option2": "M",
             "title": "Black / M", "inventory_management": None, "inventory_quantity": 0, "image_id": 9, "sku": "C-BK-M"},
            {"id": 2, "price": "89.00", "compare_at_price": "109.00", "option1": "Black", "option2": "L",
             "title": "Black / L", "inventory_management": "shopify", "inventory_quantity": 0,
             "inventory_policy": "deny", "sku": "C-BK-L"},
        ],
    }, {
        "id": 222, "title": "Draft tee", "handle": "draft-tee", "status": "draft",
        "images": [{"src": "https://cdn.shopify.com/x.jpg"}], "variants": [{"id": 3, "price": "40"}],
    }]


class TestAuthGuard(unittest.TestCase):
    def test_normalize_shop_rejects_foreign_hosts(self):
        self.assertEqual(normalize_shop("maisongrozavu"), SHOP)
        self.assertEqual(normalize_shop("https://MaisonGrozavu.myshopify.com/admin"), SHOP)
        for bad in ("attacker.example", "' or '1'='1' --", "<script>", "evil.com/.myshopify.com", "", None):
            self.assertIsNone(normalize_shop(bad), bad)

    def test_session_token_checks(self):
        self.assertEqual(verify_session_token(make_session_token())["_shop"], SHOP)
        self.assertIsNone(verify_session_token(make_session_token(secret="wrong")))
        self.assertIsNone(verify_session_token(make_session_token(aud="other_app")))
        self.assertIsNone(verify_session_token(make_session_token(exp_offset=-120)))
        self.assertIsNone(verify_session_token(make_session_token(nbf_offset=300)))
        self.assertIsNone(verify_session_token("not.a.jwt"))

    def test_webhook_hmac(self):
        body = b'{"id": 1}'
        good = base64.b64encode(hmac.new(API_SECRET.encode(), body, hashlib.sha256).digest()).decode()
        self.assertTrue(verify_webhook_hmac(body, good))
        self.assertFalse(verify_webhook_hmac(body + b" ", good))
        self.assertFalse(verify_webhook_hmac(body, None))
        self.assertFalse(verify_webhook_hmac(body, good, secret=""))


class TestProtectedRoutes(unittest.TestCase):
    PROTECTED_GET = ["/api/snapshot", "/api/briefing", "/api/autopilot/status", "/api/settings/delivery",
                     "/api/settings/whatsapp", "/api/settings/notifications", "/api/post-delivery/queue",
                     "/api/history", "/api/seo/audit", "/api/seo/logs", "/api/compliance/stats",
                     "/api/debug/shops", "/api/growth/seo", "/api/growth/radar", "/api/growth/google-suggest"]
    PROTECTED_POST = [("/api/autopilot/dispatch", {"shop": SHOP}), ("/api/email/test", {"to_email": "a@b.com"}),
                      ("/api/whatsapp/test", {"to_phone": "+34600000000"}), ("/api/plan/upgrade", {"plan": "pro"}),
                      ("/api/settings/delivery", {"sender_email": "x@y.com"}), ("/api/seo/optimize-now", {}),
                      ("/api/chat", {"message": "hi"}), ("/api/post-delivery/sync", {}),
                      ("/api/billing/create", {}), ("/api/notifications/test", {})]

    def setUp(self):
        db.init_db()
        self.client = TestClient(main.app)

    def test_every_sensitive_route_requires_auth(self):
        for path in self.PROTECTED_GET:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 401, path)
        for path, body in self.PROTECTED_POST:
            r = self.client.post(path, json=body)
            self.assertEqual(r.status_code, 401, path)
        r = self.client.get("/api/snapshot", headers={"X-Jarvis-Key": "wrong-key-wrong-key"})
        self.assertEqual(r.status_code, 401)

    def test_public_routes_stay_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/status").status_code, 200)
        self.assertEqual(self.client.get("/privacy").status_code, 200)

    def test_session_token_is_pinned_to_its_shop(self):
        headers = {"Authorization": f"Bearer {make_session_token()}"}
        self.assertEqual(self.client.get(f"/api/snapshot?shop={SHOP}", headers=headers).status_code, 200)
        r = self.client.get("/api/snapshot?shop=other-store.myshopify.com", headers=headers)
        self.assertEqual(r.status_code, 403)

    def test_invalid_shop_is_rejected_and_never_contacted(self):
        with patch.object(main, "ShopifyClient") as client_cls:
            r = self.client.get("/api/snapshot?shop=attacker.example", headers=AUTH)
            self.assertEqual(r.status_code, 400)
            client_cls.assert_not_called()

    def test_unknown_shop_is_not_auto_provisioned(self):
        shop = "brand-new-store.myshopify.com"
        r = self.client.get(f"/api/snapshot?shop={shop}", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["connected"])
        self.assertIsNone(db.get_shop(shop))


class TestTruthfulSnapshot(unittest.TestCase):
    def setUp(self):
        db.init_db()
        main._SNAPSHOT_CACHE.clear()
        self.client = TestClient(main.app)

    def test_not_connected_snapshot_has_no_invented_numbers(self):
        with patch.object(main, "get_shop_or_404", return_value={"shop": SHOP, "access_token": "shpat_live_token",
                                                                "shop_name": "Grozavu", "plan": "free"}):
            snap = self.client.get("/api/snapshot", headers=AUTH).json()
        self.assertFalse(snap["connected"])
        self.assertEqual(snap["data_source"], "none")
        for k in ("orders_30d", "orders_today", "revenue_30d", "revenue_today", "aov", "abandoned_carts"):
            self.assertEqual(snap[k], 0, k)
        self.assertEqual(snap["vip_customers"], [])
        self.assertNotIn("Elena", json.dumps(snap))
        self.assertNotIn("Silk", json.dumps(snap))

    def test_shopify_failure_gives_empty_snapshot_with_reason(self):
        fake = MagicMock()
        fake.get_store_snapshot = AsyncMock(side_effect=RuntimeError("429 Too Many Requests"))
        with patch.object(main, "get_shop_or_404", return_value={"shop": SHOP, "access_token": "shpat_0123456789abcdef",
                                                                "shop_name": "Grozavu"}), \
                patch.object(main, "ShopifyClient", return_value=fake):
            snap = self.client.get("/api/snapshot", headers=AUTH).json()
        self.assertFalse(snap["connected"])
        self.assertEqual(snap["revenue_30d"], 0)
        self.assertIn("429", snap["data_error"])


class TestSettingsSecrets(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.client = TestClient(main.app)
        self.shop = "secrets-test.myshopify.com"
        current = db.get_shop_settings(self.shop)
        current.update({"resend_api_key": "re_SECRET123", "twilio_auth_token": "tw_SECRET",
                        "telegram_bot_token": "123:SECRET", "whatsapp_api_token": "EAA_SECRET",
                        "smtp_password": "pw_SECRET"})
        db.save_shop_settings(self.shop, current)

    def test_secrets_are_never_returned(self):
        for path in ("/api/settings/delivery", "/api/settings/whatsapp", "/api/settings/notifications"):
            body = self.client.get(f"{path}?shop={self.shop}", headers=AUTH).text
            self.assertNotIn("SECRET", body, path)

    def test_saving_masked_value_keeps_existing_secret(self):
        r = self.client.post("/api/settings/delivery", headers=AUTH,
                             json={"shop": self.shop, "resend_api_key": "••••••••", "sender_name": "Grozavu"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("SECRET", r.text)
        self.assertEqual(db.get_shop_settings(self.shop)["resend_api_key"], "re_SECRET123")


class TestWebhooks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _signed(self, body: bytes):
        sig = base64.b64encode(hmac.new(API_SECRET.encode(), body, hashlib.sha256).digest()).decode()
        return {"X-Shopify-Hmac-Sha256": sig, "X-Shopify-Shop-Domain": SHOP, "Content-Type": "application/json"}

    def test_unsigned_webhooks_are_rejected(self):
        for path in ("/webhooks/orders/create", "/webhooks/orders/cancelled", "/webhooks/customers/redact",
                     "/webhooks/customers/data_request", "/webhooks/shop/redact", "/webhooks/app/uninstalled"):
            r = self.client.post(path, content=b'{"id": 1}', headers={"X-Shopify-Shop-Domain": SHOP})
            self.assertEqual(r.status_code, 401, path)

    def test_signed_order_webhook_reconciles(self):
        body = json.dumps({"id": 5, "checkout_id": 77, "email": "a@b.com", "total_price": "10"}).encode()
        with patch.object(main.cadence_mgr, "reconcile_order", return_value={"converted": 0, "attributed": False}) as conv:
            r = self.client.post("/webhooks/orders/create", content=body, headers=self._signed(body))
        self.assertEqual(r.status_code, 200)
        conv.assert_called_once()

    def test_customers_redact_calls_db(self):
        body = json.dumps({"shop_domain": SHOP, "customer": {"email": "x@y.com", "phone": "+34600"}}).encode()
        with patch.object(main.db, "redact_customer", create=True, return_value={}) as red:
            r = self.client.post("/webhooks/customers/redact", content=body, headers=self._signed(body))
        self.assertEqual(r.status_code, 200)
        red.assert_called_once_with(SHOP, email="x@y.com", phone="+34600", order_ids=[])


class TestUnsubscribe(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.client = TestClient(main.app)

    def test_get_only_asks_for_confirmation_and_escapes(self):
        """Mail security scanners open every link: a GET must never unsubscribe anybody by itself."""
        payload = '<img src=x onerror=alert(1)>@x.com'
        with patch.object(main.db, "record_opt_out", return_value=True) as opt:
            r = self.client.get("/api/unsubscribe", params={"email": payload, "shop": SHOP})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("<img", r.text)
        self.assertIn("&lt;img", r.text)
        self.assertIn('method="post"', r.text)
        opt.assert_not_called()

    def test_confirmation_button_records_opt_out(self):
        with patch.object(main.db, "record_opt_out", return_value=True) as opt:
            r = self.client.post("/api/unsubscribe", data={"email": "ana@x.com", "shop": SHOP, "lang": "es",
                                                           "confirm": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Te has dado de baja", r.text)
        opt.assert_called_once_with(SHOP, email="ana@x.com")

    def test_public_status_without_shop_but_details_need_auth(self):
        self.assertEqual(self.client.get("/api/status").status_code, 200)
        self.assertEqual(self.client.get(f"/api/status?shop={SHOP}").status_code, 401)
        self.assertEqual(self.client.get(f"/api/status?shop={SHOP}", headers=AUTH).status_code, 200)

    def test_api_docs_are_not_public(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.get("/api/google/feed-validation").status_code, 401)

    def test_empty_email_is_not_a_fake_success(self):
        r = self.client.get("/api/unsubscribe?email=")
        self.assertEqual(r.status_code, 400)

    def test_one_click_post(self):
        with patch.object(main.db, "record_opt_out", return_value=True) as opt:
            r = self.client.post(f"/api/unsubscribe?email=a%40b.com&shop={SHOP}",
                                 data={"List-Unsubscribe": "One-Click"})
        self.assertEqual(r.status_code, 200)
        opt.assert_called_once_with(SHOP, email="a@b.com")


class TestGoogleFeed(unittest.TestCase):
    def setUp(self):
        main._FEED_CACHE.clear()
        self.client = TestClient(main.app)

    def test_feed_items_one_per_variant_and_only_real_data(self):
        items, skipped = build_feed_items(sample_products(), shop_domain="maisongrozavu.com", brand="Grozavu")
        self.assertEqual(len(items), 2)
        self.assertEqual({i["item_group_id"] for i in items}, {"shopify_111"})
        black_m = next(i for i in items if i["id"] == "shopify_111_1")
        self.assertEqual(black_m["color"], "Black")
        self.assertEqual(black_m["size"], "M")
        self.assertEqual(black_m["availability"], "in_stock")  # untracked (Printful) variant
        self.assertEqual(black_m["link"], "https://maisongrozavu.com/products/grozavu-ss26-crewneck?variant=1")
        self.assertIn("&", black_m["description"])  # unescaped text, escaped once by XML writer
        black_l = next(i for i in items if i["id"] == "shopify_111_2")
        self.assertEqual(black_l["availability"], "out_of_stock")
        self.assertEqual(black_l["price"], "109.00 EUR")
        self.assertEqual(black_l["sale_price"], "89.00 EUR")
        self.assertTrue(any(s["product"] == "Draft tee" for s in skipped))

    def test_feed_xml_is_valid_and_not_double_escaped(self):
        xml_feed = build_google_merchant_xml(sample_products(), shop_domain="maisongrozavu.com", store_name="Grozavu")
        self.assertNotIn("&amp;amp;", xml_feed)
        val = validate_google_merchant_feed(xml_feed)
        self.assertTrue(val["valid"], val["errors"])
        self.assertEqual(val["items_count"], 2)

    def test_empty_products_never_produce_fake_items(self):
        xml_feed = build_google_merchant_xml([], shop_domain="maisongrozavu.com")
        self.assertNotIn("Mătase", xml_feed)
        self.assertNotIn("<item>", xml_feed)
        self.assertFalse(validate_google_merchant_feed(xml_feed)["valid"])

    def test_validator_rejects_bad_values(self):
        bad = ('<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel><title>t</title><link>l</link>'
               '<description>d</description><item><g:id>1</g:id><g:title>T</g:title><g:description>D</g:description>'
               '<g:link>not a url</g:link><g:image_link>https://x/y.jpg</g:image_link><g:availability>maybe</g:availability>'
               '<g:price>free!!</g:price><g:brand>B</g:brand><g:condition>new</g:condition></item></channel></rss>')
        val = validate_google_merchant_feed(bad)
        self.assertFalse(val["valid"])
        joined = " ".join(val["errors"])
        self.assertIn("availability", joined)
        self.assertIn("price", joined)
        self.assertIn("link", joined)

    def test_feed_endpoint_returns_503_instead_of_fake_products(self):
        with patch.object(main, "get_shop_or_404", return_value={"shop": SHOP, "access_token": ""}):
            r = self.client.get("/feeds/google-merchant.xml")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("<item>", r.text)

    def test_feed_endpoint_with_real_products(self):
        fake = MagicMock()
        fake.get_active_products = AsyncMock(return_value=sample_products())
        with patch.object(main, "get_shop_or_404", return_value={"shop": SHOP, "access_token": "shpat_0123456789abcdef"}), \
                patch.object(main, "ShopifyClient", return_value=fake):
            r = self.client.get("/feeds/google-merchant.xml")
            v = self.client.get("/api/google/feed-validation", headers=AUTH).json()
        self.assertEqual(r.status_code, 200)
        root = ET.fromstring(r.content)
        self.assertEqual(len(root.find("channel").findall("item")), 2)
        self.assertTrue(v["valid"], v["errors"])
        self.assertTrue(v["feed_url"].endswith("/feeds/google-merchant.xml"))


class TestAutopilotDispatch(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_dispatch_without_shopify_is_honest(self):
        with patch.object(main, "get_shop_or_404", return_value={"shop": SHOP, "access_token": ""}):
            body = self.client.post("/api/autopilot/dispatch", headers=AUTH, json={"shop": SHOP}).json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["dispatched_count"], 0)


if __name__ == "__main__":
    unittest.main()

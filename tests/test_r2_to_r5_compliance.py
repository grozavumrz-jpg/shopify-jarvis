"""
Unit and Integration Tests for Jarvis R2-R5 Enhancements:
- R2: Google Merchant RSS 2.0 Feed & On-Store Product SEO Optimizer
- R3: Autonomous Follow-ups & Consent Guard (GDPR / CAN-SPAM / Quiet Hours / Frequency Caps)
- R4: Deliverability & Live DNS Audit (SPF/DKIM/DMARC / List-Unsubscribe One-Click)
- R5: Truthful Reporting Endpoints & Compliance Tracking
"""

import unittest
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

# Add project root and backend to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

try:
    from tests.auth_helpers import AUTH_HEADERS, webhook_headers, auth_headers  # noqa: E402
except ImportError:  # running with tests/ as top-level dir
    from auth_helpers import AUTH_HEADERS, webhook_headers, auth_headers  # noqa: E402
import database as db
from google_merchant_feed import (
    build_google_merchant_xml,
    validate_google_merchant_feed,
    DEFAULT_LUXURY_PRODUCTS
)
from seo_optimizer import ProductSEOOptimizer
from compliance_guard import is_quiet_hours, can_dispatch_to_customer, log_customer_dispatch
from deliverability_checker import DeliverabilityChecker
from starlette.testclient import TestClient
from main import app
import main as main_mod


class TestGoogleMerchantFeed(unittest.TestCase):
    def setUp(self):
        self.shop_domain = "maisongrozavu.com"
        self.store_name = "Maison Grozavu"

    def test_no_products_means_no_fake_feed_items(self):
        """Without real Shopify products the feed must be empty — never invented 'luxury' products."""
        self.assertEqual(DEFAULT_LUXURY_PRODUCTS, [])
        xml_feed = build_google_merchant_xml(
            products=None,
            shop_domain=self.shop_domain,
            store_name=self.store_name,
            currency="EUR"
        )
        self.assertIn("<?xml", xml_feed)
        self.assertIn("<rss xmlns:g=\"http://base.google.com/ns/1.0\" version=\"2.0\"", xml_feed)
        self.assertNotIn("<item>", xml_feed)
        self.assertNotIn("Mătase", xml_feed)

        val = validate_google_merchant_feed(xml_feed)
        self.assertFalse(val["valid"])
        self.assertEqual(val["items_count"], 0)

    def test_custom_products_feed_generation_and_escaping(self):
        """Test custom products with special XML characters (<, >, &, \") are safely escaped."""
        custom_products = [
            {
                "id": 9991,
                "title": "Rochie din Mătase & Dantelă <Pretiosa>",
                "body_html": "<p>Rochie splendidă de seară & bal 'Black Tie'.</p>",
                "handle": "rochie-matase-dantela",
                "images": [{"src": "https://maisongrozavu.com/img1.jpg"}],
                "status": "active",
                "variants": [{"id": 1, "price": "390.00", "inventory_quantity": 4, "inventory_policy": "deny"}],
                "product_type": "Rochii de Seară"
            }
        ]
        xml_feed = build_google_merchant_xml(
            products=custom_products,
            shop_domain=self.shop_domain,
            store_name=self.store_name,
            currency="EUR"
        )
        self.assertIn("shopify_9991", xml_feed)
        self.assertIn("<g:price>390.00 EUR</g:price>", xml_feed)
        self.assertIn("<g:availability>in_stock</g:availability>", xml_feed)
        
        # XML parsing validation
        val = validate_google_merchant_feed(xml_feed)
        self.assertTrue(val["valid"], f"Validation failed: {val['errors']}")
        self.assertEqual(val["items_count"], 1)

    def test_validator_rejects_malformed_xml(self):
        """Test validator flags missing tags or broken XML."""
        bad_xml = "<rss><channel><item><title>Test</title></item></channel></rss>"
        val = validate_google_merchant_feed(bad_xml)
        self.assertFalse(val["valid"])
        self.assertTrue(len(val["errors"]) > 0)


class TestProductSEOOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = ProductSEOOptimizer(brand_name="Maison Grozavu", domain="maisongrozavu.com")

    def test_audit_identifies_short_title_and_description(self):
        """Test SEO audit detects poor title and description lengths and offers actionable suggestions."""
        product = {
            "id": 101,
            "title": "Sacou",  # Too short (< 25 chars)
            "body_html": "Sacou negru.",  # Too short (< 80 chars)
            "images": [{"src": "https://maisongrozavu.com/s1.jpg", "alt": ""}],  # Missing alt
            "handle": "sacou-negru"
        }
        audit = self.optimizer.audit_product_seo(product)
        self.assertTrue(audit["needs_optimization"])
        self.assertLess(audit["seo_score"], 70)
        self.assertGreaterEqual(len(audit["issues"]), 2)
        
        # Verify optimized title contains brand and has good length
        opt_title = audit["optimized_title"]
        self.assertIn("Maison Grozavu", opt_title)
        self.assertGreaterEqual(len(opt_title), 25)
        self.assertLessEqual(len(opt_title), 70)

        # Verify optimized meta description length (100-160 chars)
        opt_desc = audit["optimized_description"]
        self.assertGreaterEqual(len(opt_desc), 100)
        self.assertLessEqual(len(opt_desc), 160)

    def test_schema_org_json_ld_generation(self):
        """Test Schema.org Product JSON-LD output follows Google rich snippet standards."""
        product = {
            "id": 202,
            "title": "Rochie de Seară Noir",
            "body_html": "Rochie superbă din mătase pură.",
            "handle": "rochie-seara-noir",
            "images": [{"src": "https://maisongrozavu.com/rochie.jpg"}],
            "variants": [{"price": "450.00"}]
        }
        schema = self.optimizer.generate_json_ld_schema(product)
        self.assertEqual(schema["@context"], "https://schema.org")
        self.assertEqual(schema["@type"], "Product")
        self.assertEqual(schema["name"], "Rochie de Seară Noir")
        self.assertEqual(schema["brand"]["name"], "Maison Grozavu")
        self.assertEqual(schema["offers"]["price"], "450.00")
        self.assertEqual(schema["offers"]["priceCurrency"], "EUR")


class TestComplianceGuardAndConsent(unittest.TestCase):
    def setUp(self):
        self.shop_domain = "maisongrozavu.myshopify.com"
        db.init_db()

    def test_quiet_hours_calculation(self):
        """
        Quiet hours are 21:00-09:00 in Europe/Madrid (the store's timezone), DST-correct.
        2026-10-28 is after the DST change (CET = UTC+1); 2026-07-15 is summer (CEST = UTC+2).
        """
        self.assertFalse(is_quiet_hours(datetime(2026, 10, 28, 19, 0, tzinfo=timezone.utc)))  # 20:00 Madrid
        self.assertTrue(is_quiet_hours(datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)))   # 21:00 Madrid
        self.assertTrue(is_quiet_hours(datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)))   # 00:00 Madrid
        self.assertTrue(is_quiet_hours(datetime(2026, 10, 28, 7, 30, tzinfo=timezone.utc)))   # 08:30 Madrid
        self.assertFalse(is_quiet_hours(datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)))   # 09:00 Madrid
        self.assertFalse(is_quiet_hours(datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)))  # 13:00 Madrid
        self.assertTrue(is_quiet_hours(datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)))    # 21:00 CEST
        self.assertFalse(is_quiet_hours(datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc)))    # 09:00 CEST

    def test_consent_and_opt_out_flow(self):
        """Unknown consent = NO consent; explicit consent allows; opt-out always wins."""
        test_email = f"test_compliance_{datetime.now().timestamp()}@example.com"
        daytime = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

        self.assertFalse(db.is_consent_given(self.shop_domain, email=test_email))
        allowed, reason = can_dispatch_to_customer(self.shop_domain, email=test_email, now_dt=daytime)
        self.assertFalse(allowed)

        db.record_marketing_consent(self.shop_domain, email=test_email, accepts_marketing=True)
        self.assertTrue(db.is_consent_given(self.shop_domain, email=test_email))

        db.record_opt_out(self.shop_domain, email=test_email)
        self.assertFalse(db.is_consent_given(self.shop_domain, email=test_email))
        allowed, reason = can_dispatch_to_customer(self.shop_domain, email=test_email, now_dt=daytime)
        self.assertFalse(allowed)
        self.assertIn("opted out", reason.lower())

        # A later checkout saying "accepts marketing" must not undo an unsubscribe
        db.record_marketing_consent(self.shop_domain, email=test_email, accepts_marketing=True, source="checkout")
        self.assertFalse(db.is_consent_given(self.shop_domain, email=test_email))

    def test_frequency_capping_enforcement(self):
        """A new marketing sequence is blocked if the customer got a message in the last 72 hours."""
        test_email = f"freq_test_{datetime.now().timestamp()}@example.com"
        daytime = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
        db.record_marketing_consent(self.shop_domain, email=test_email, accepts_marketing=True)

        allowed, reason = can_dispatch_to_customer(
            self.shop_domain, email=test_email, now_dt=daytime, sequence_key="cart:freq1")
        self.assertTrue(allowed, f"First dispatch blocked: {reason}")
        log_customer_dispatch(self.shop_domain, recipient=test_email, channel="email",
                              message_type="abandoned_cart_stage_1", sequence_key="cart:freq1", sent_at=daytime)

        # A DIFFERENT sequence within 72h is blocked
        allowed2, reason2 = can_dispatch_to_customer(
            self.shop_domain, email=test_email, now_dt=daytime, sequence_key="cart:freq2")
        self.assertFalse(allowed2)
        self.assertIn("72", reason2)

        # The follow-up stage of the SAME cart sequence is allowed (stages 2-3)
        allowed3, reason3 = can_dispatch_to_customer(
            self.shop_domain, email=test_email, now_dt=daytime, sequence_key="cart:freq1")
        self.assertTrue(allowed3, reason3)


class TestDeliverabilityChecker(unittest.IsolatedAsyncioTestCase):
    """Resend needs SPF+MX on send.<domain>, DKIM on resend._domainkey.<domain>, and DMARC."""

    def _dns(self, overrides=None):
        records = {
            ("send.maisongrozavu.com", "TXT"): ["v=spf1 include:amazonses.com ~all"],
            ("send.maisongrozavu.com", "MX"): ["10 feedback-smtp.eu-west-1.amazonses.com"],
            ("resend._domainkey.maisongrozavu.com", "TXT"): ["p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDktEwN4K3kdMMS619dSeOticKcCFApbGKnG29mL7OasB5apPaY7UUFhjbhTgJLOg0pGJPWOfgIUr9ZG20eWF3iZ6Cv0MVJV5rleUZC5aeRPEKLk1geRgqieq+3gm+HYXE6tbdbE3xVIYqekhe3mHQLDwlNvc4i/0JfTRjFUgx8FQIDAQAB"],
            ("_dmarc.maisongrozavu.com", "TXT"): ["v=DMARC1; p=quarantine; rua=mailto:info@maisongrozavu.com"],
            ("maisongrozavu.com", "TXT"): ["v=spf1 include:_spf.hostedemail.com ~all"],
        }
        records.update(overrides or {})

        async def fake(name, rtype="TXT"):
            return records.get((name, rtype), [])
        return fake

    async def test_audit_domain_with_complete_records(self):
        with patch.object(DeliverabilityChecker, "_query_records", side_effect=self._dns()):
            res = await DeliverabilityChecker(domain="maisongrozavu.com").audit_domain("maisongrozavu.com")
        for key in ("spf", "mx", "dkim", "dmarc"):
            self.assertEqual(res["checks"][key]["status"], "ok", key)
        self.assertEqual(res["missing_records"], [])
        self.assertNotIn("garantat", str(res).lower())

    async def test_audit_domain_live_like_records_missing_send_subdomain(self):
        """Today's real DNS: DKIM present, DMARC p=none, but nothing on send.maisongrozavu.com."""
        with patch.object(DeliverabilityChecker, "_query_records", side_effect=self._dns({
            ("send.maisongrozavu.com", "TXT"): [], ("send.maisongrozavu.com", "MX"): [],
            ("_dmarc.maisongrozavu.com", "TXT"): ["v=DMARC1; p=none"]})):
            res = await DeliverabilityChecker(domain="maisongrozavu.com").audit_domain("maisongrozavu.com")
        self.assertEqual(res["checks"]["spf"]["status"], "missing")
        self.assertEqual(res["checks"]["mx"]["status"], "missing")
        self.assertEqual(res["checks"]["dkim"]["status"], "ok")
        hosts = " ".join(str(r) for r in res["records_to_add"])
        self.assertIn("send", hosts)
        self.assertIn("amazonses.com", hosts)

    async def test_dns_unreachable_is_unknown_not_missing(self):
        from deliverability_checker import DNSLookupError

        async def boom(name, rtype="TXT"):
            raise DNSLookupError("resolvers unreachable")
        with patch.object(DeliverabilityChecker, "_query_records", side_effect=boom):
            res = await DeliverabilityChecker(domain="maisongrozavu.com").audit_domain("maisongrozavu.com")
        self.assertEqual(res["checks"]["spf"]["status"], "unknown")
        self.assertIsNone(res["score"])


class TestE2EEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, headers=AUTH_HEADERS)

    def _real_products(self):
        return [{"id": 7, "title": "Grozavu Boxy Tee", "handle": "grozavu-boxy-tee", "status": "active",
                 "body_html": "<p>170 g/m² boxy tee.</p>", "options": [{"name": "Size", "position": 1}],
                 "images": [{"src": "https://cdn.shopify.com/tee.jpg"}],
                 "variants": [{"id": 70, "price": "45.00", "option1": "M"}, {"id": 71, "price": "45.00", "option1": "L"}]}]

    def _patched(self):
        fake = MagicMock()
        fake.get_active_products = AsyncMock(return_value=self._real_products())
        main_mod._FEED_CACHE.clear()
        return (patch.object(main_mod, "get_shop_or_404", return_value={"shop": "maisongrozavu.myshopify.com",
                                                                        "access_token": "shpat_0123456789abcdef"}),
                patch.object(main_mod, "ShopifyClient", return_value=fake))

    def test_google_merchant_feed_unavailable_without_shopify(self):
        """Without a Shopify connection the feed answers 503 (Google retries) instead of fake products."""
        main_mod._FEED_CACHE.clear()
        with patch.object(main_mod, "get_shop_or_404", return_value={"shop": "maisongrozavu.myshopify.com", "access_token": ""}):
            resp = self.client.get("/api/google/feed.xml")
        self.assertEqual(resp.status_code, 503)

    def test_google_merchant_feed_xml_endpoint(self):
        """Test GET /api/google/feed.xml returns valid XML with application/xml header."""
        p1, p2 = self._patched()
        with p1, p2:
            resp = self.client.get("/api/google/feed.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/xml", resp.headers.get("content-type", ""))
        self.assertIn("<rss xmlns:g=\"http://base.google.com/ns/1.0\"", resp.text)
        self.assertIn("<g:price>", resp.text)

    def test_google_merchant_validation_endpoint(self):
        """Test GET /api/google/feed-validation returns valid spec status."""
        p1, p2 = self._patched()
        with p1, p2:
            resp = self.client.get("/api/google/feed-validation")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("valid"))
        self.assertGreater(data.get("items_count", 0), 0)

    def test_seo_audit_endpoint(self):
        """Test GET /api/seo/audit returns catalog SEO posture."""
        resp = self.client.get("/api/seo/audit")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("audits", data)
        self.assertIn("products_audited", data)

    def test_unsubscribe_endpoint_renders_html_and_opts_out(self):
        """Test GET /api/unsubscribe records opt-out and displays confirmation."""
        unsub_email = f"unsub_{datetime.now().timestamp()}@test.ro"
        resp = self.client.get(f"/api/unsubscribe?email={unsub_email}&shop=maisongrozavu.myshopify.com&lang=ro")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Te dezabonezi?", resp.text)  # GET = confirmation page only
        resp = self.client.post("/api/unsubscribe", data={"email": unsub_email, "shop": "maisongrozavu.myshopify.com",
                                                          "lang": "ro", "confirm": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Grozavu", resp.text)
        self.assertIn("Te-ai dezabonat cu succes", resp.text)

        # Verify DB is updated
        self.assertFalse(db.is_consent_given("maisongrozavu.myshopify.com", email=unsub_email))


if __name__ == "__main__":
    unittest.main()

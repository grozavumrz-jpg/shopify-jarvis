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
from unittest.mock import patch, AsyncMock

# Add project root and backend to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

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


class TestGoogleMerchantFeed(unittest.TestCase):
    def setUp(self):
        self.shop_domain = "maisongrozavu.com"
        self.store_name = "Maison Grozavu"

    def test_default_products_feed_generation(self):
        """Test default feed generation contains all 5 luxury products and required tags."""
        xml_feed = build_google_merchant_xml(
            products=None,
            shop_domain=self.shop_domain,
            store_name=self.store_name,
            currency="EUR"
        )
        self.assertIn("<?xml", xml_feed)
        self.assertIn("<rss xmlns:g=\"http://base.google.com/ns/1.0\" version=\"2.0\"", xml_feed)
        self.assertIn("<g:title>", xml_feed)
        self.assertIn("<g:price>", xml_feed)
        self.assertIn("Maison Grozavu", xml_feed)
        
        val = validate_google_merchant_feed(xml_feed)
        self.assertTrue(val["valid"], f"Validation failed: {val['errors']}")
        self.assertEqual(val["items_count"], 5)
        self.assertEqual(len(val["errors"]), 0)

    def test_custom_products_feed_generation_and_escaping(self):
        """Test custom products with special XML characters (<, >, &, \") are safely escaped."""
        custom_products = [
            {
                "id": 9991,
                "title": "Rochie din Mătase & Dantelă <Pretiosa>",
                "body_html": "<p>Rochie splendidă de seară & bal 'Black Tie'.</p>",
                "handle": "rochie-matase-dantela",
                "images": [{"src": "https://maisongrozavu.com/img1.jpg"}],
                "variants": [{"price": "390.00", "inventory_quantity": 4, "inventory_policy": "deny"}],
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
        Verify quiet hours (21:00 to 09:00 Bucharest time).
        Bucharest is UTC+2 (standard) / UTC+3 (DST). With UTC+2:
        - UTC 19:00 -> Bucharest 21:00 -> Quiet hours TRUE
        - UTC 23:00 -> Bucharest 01:00 -> Quiet hours TRUE
        - UTC 06:00 -> Bucharest 08:00 -> Quiet hours TRUE
        - UTC 08:00 -> Bucharest 10:00 -> Quiet hours FALSE
        - UTC 15:00 -> Bucharest 17:00 -> Quiet hours FALSE
        """
        dt_night_start = datetime(2026, 10, 28, 19, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_quiet_hours(dt_night_start))

        dt_midnight = datetime(2026, 10, 28, 23, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_quiet_hours(dt_midnight))

        dt_early_morning = datetime(2026, 10, 28, 6, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_quiet_hours(dt_early_morning))

        dt_daytime = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_quiet_hours(dt_daytime))

    def test_consent_and_opt_out_flow(self):
        """Test recording consent, opt-out, and checking permissions."""
        test_email = f"test_compliance_{datetime.now().timestamp()}@example.com"

        # Initially consent is assumed true by default if no opt-out is recorded
        self.assertTrue(db.is_consent_given(self.shop_domain, email=test_email))

        # Explicitly opt-out
        db.record_opt_out(self.shop_domain, email=test_email)
        self.assertFalse(db.is_consent_given(self.shop_domain, email=test_email))

        # Can dispatch should block opted-out customer
        daytime = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
        allowed, reason = can_dispatch_to_customer(
            self.shop_domain, email=test_email, now_dt=daytime
        )
        self.assertFalse(allowed)
        self.assertIn("opted out", reason.lower())

    def test_frequency_capping_enforcement(self):
        """Test that customer cannot receive more than 1 message per 72 hours."""
        test_email = f"freq_test_{datetime.now().timestamp()}@example.com"
        daytime = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

        # First dispatch check should pass
        allowed, reason = can_dispatch_to_customer(
            self.shop_domain, email=test_email, now_dt=daytime
        )
        self.assertTrue(allowed, f"First dispatch blocked: {reason}")

        # Record a dispatch
        log_customer_dispatch(self.shop_domain, recipient=test_email, channel="email", message_type="cart_reminder")

        # Second dispatch within 72 hours should be blocked by frequency cap
        allowed2, reason2 = can_dispatch_to_customer(
            self.shop_domain, email=test_email, now_dt=daytime
        )
        self.assertFalse(allowed2)
        self.assertIn("Frequency cap", reason2)


class TestDeliverabilityChecker(unittest.IsolatedAsyncioTestCase):
    @patch.object(DeliverabilityChecker, "_query_txt_records")
    async def test_audit_domain_with_perfect_records(self, mock_query):
        """Test domain with SPF, DKIM, DMARC scores 100/100 and has 0 missing records."""
        async def side_effect(name: str):
            if name == "maisongrozavu.com":
                return ["v=spf1 include:resend.com ~all"]
            elif name == "_dmarc.maisongrozavu.com":
                return ["v=DMARC1; p=reject; sp=reject; adkim=r; aspf=r"]
            elif name == "resend._domainkey.maisongrozavu.com":
                return ["k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQ..."]
            return []

        mock_query.side_effect = side_effect
        checker = DeliverabilityChecker(domain="maisongrozavu.com")
        res = await checker.audit_domain("maisongrozavu.com")

        self.assertEqual(res["score"], 100)
        self.assertIn("Excelent", res["rating"])
        self.assertEqual(len(res["missing_records"]), 0)
        self.assertTrue(res["checks"]["spf"]["configured"])
        self.assertTrue(res["checks"]["dkim"]["configured"])
        self.assertTrue(res["checks"]["dmarc"]["configured"])

    @patch.object(DeliverabilityChecker, "_query_txt_records")
    async def test_audit_domain_with_missing_spf(self, mock_query):
        """Test domain missing SPF is flagged and receives a lower score with exact remediation instructions."""
        async def side_effect(name: str):
            if name == "maisongrozavu.com":
                return []
            elif name == "_dmarc.maisongrozavu.com":
                return ["v=DMARC1; p=none"]
            elif name == "resend._domainkey.maisongrozavu.com":
                return ["k=rsa; p=12345"]
            return []

        mock_query.side_effect = side_effect
        checker = DeliverabilityChecker(domain="maisongrozavu.com")
        res = await checker.audit_domain("maisongrozavu.com")

        self.assertEqual(res["score"], 65)  # 35 points deducted for missing SPF
        self.assertFalse(res["checks"]["spf"]["configured"])
        self.assertEqual(len(res["missing_records"]), 1)
        self.assertIn("v=spf1", res["missing_records"][0]["recommended_value"])


class TestE2EEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_google_merchant_feed_xml_endpoint(self):
        """Test GET /api/google/feed.xml returns valid XML with application/xml header."""
        resp = self.client.get("/api/google/feed.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/xml", resp.headers.get("content-type", ""))
        self.assertIn("<rss xmlns:g=\"http://base.google.com/ns/1.0\"", resp.text)
        self.assertIn("<g:price>", resp.text)

    def test_google_merchant_validation_endpoint(self):
        """Test GET /api/google/feed-validation returns valid spec status."""
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
        resp = self.client.get(f"/api/unsubscribe?email={unsub_email}&shop=maisongrozavu.myshopify.com")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Maison Grozavu", resp.text)
        self.assertIn("Te-ai dezabonat cu succes", resp.text)

        # Verify DB is updated
        self.assertFalse(db.is_consent_given("maisongrozavu.myshopify.com", email=unsub_email))


if __name__ == "__main__":
    unittest.main()

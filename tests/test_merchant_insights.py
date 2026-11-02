"""
Bounce/complaint suppression via Resend webhooks, merchant alerts (downtime, repeated failures)
and the weekly report.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

try:
    from tests.auth_helpers import AUTH_HEADERS  # noqa: E402
except ImportError:  # pragma: no cover
    from auth_helpers import AUTH_HEADERS  # noqa: E402

import auth_guard  # noqa: E402
import database as db  # noqa: E402
import main  # noqa: E402
from mobile_notifier import MobileNotifier  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

SECRET = "whsec_" + base64.b64encode(b"resend-test-signing-key-123456").decode()


def svix_headers(body: bytes, secret: str = SECRET, ts: int = None, msg_id: str = "msg_1") -> dict:
    ts = int(time.time()) if ts is None else ts
    key = base64.b64decode(secret[len("whsec_"):])
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": str(ts), "svix-signature": f"v1,{sig}",
            "Content-Type": "application/json"}


class TestSvixSignature(unittest.TestCase):
    def test_valid_signature_and_rotation_list(self):
        body = b'{"type":"email.bounced"}'
        h = svix_headers(body)
        self.assertTrue(auth_guard.verify_svix_signature(body, h["svix-id"], h["svix-timestamp"],
                                                         "v1,AAAA " + h["svix-signature"], SECRET))

    def test_rejects_tampering_old_timestamps_and_missing_secret(self):
        body = b'{"type":"email.bounced"}'
        h = svix_headers(body)
        self.assertFalse(auth_guard.verify_svix_signature(body + b" ", h["svix-id"], h["svix-timestamp"], h["svix-signature"], SECRET))
        old = svix_headers(body, ts=int(time.time()) - 3600)
        self.assertFalse(auth_guard.verify_svix_signature(body, old["svix-id"], old["svix-timestamp"], old["svix-signature"], SECRET))
        self.assertFalse(auth_guard.verify_svix_signature(body, h["svix-id"], h["svix-timestamp"], h["svix-signature"], ""))


class TestResendWebhook(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.client = TestClient(main.app)
        self.env = patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": SECRET})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _post(self, payload: dict, headers=None):
        body = json.dumps(payload).encode()
        return self.client.post("/webhooks/resend", content=body, headers=headers or svix_headers(body))

    def test_hard_bounce_and_complaint_are_suppressed(self):
        bounced, complained = f"b-{uuid.uuid4().hex[:8]}@x.com", f"c-{uuid.uuid4().hex[:8]}@x.com"
        for addr in (bounced, complained):
            db.record_marketing_consent(main.default_shop(), email=addr, accepts_marketing=True)
        r1 = self._post({"type": "email.bounced", "data": {"to": [bounced], "bounce": {"type": "Permanent"}}})
        r2 = self._post({"type": "email.complained", "data": {"to": [complained]}})
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        for addr in (bounced, complained):
            self.assertEqual(db.get_consent_status(main.default_shop(), email=addr, channel="email"), db.CONSENT_OPTED_OUT)

    def test_transient_bounce_and_other_events_change_nothing(self):
        addr = f"t-{uuid.uuid4().hex[:8]}@x.com"
        db.record_marketing_consent(main.default_shop(), email=addr, accepts_marketing=True)
        self._post({"type": "email.bounced", "data": {"to": [addr], "bounce": {"type": "Transient"}}})
        self._post({"type": "email.delivered", "data": {"to": [addr]}})
        self.assertEqual(db.get_consent_status(main.default_shop(), email=addr, channel="email"), db.CONSENT_GRANTED)

    def test_unsigned_or_unconfigured_is_refused(self):
        body = json.dumps({"type": "email.complained", "data": {"to": ["x@y.com"]}}).encode()
        self.assertEqual(self.client.post("/webhooks/resend", content=body).status_code, 401)
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": ""}):
            self.assertEqual(self.client.post("/webhooks/resend", content=body, headers=svix_headers(body)).status_code, 401)


class TestMerchantAlerts(unittest.TestCase):
    def setUp(self):
        db.init_db()
        main.AUTOPILOT_STATUS["consecutive_failed_cycles"] = 0
        main.AUTOPILOT_STATUS.pop("failure_alert_sent", None)

    def tearDown(self):
        main.AUTOPILOT_STATUS["consecutive_failed_cycles"] = 0
        main.AUTOPILOT_STATUS.pop("failure_alert_sent", None)

    def test_alert_once_after_three_failed_cycles_and_once_on_recovery(self):
        with patch.object(main, "notify_merchant_text", new_callable=AsyncMock) as notify:
            for _ in range(5):
                asyncio.run(main.watchdog_after_cycle({"errors": ["Comenzi: 401 Unauthorized"]}))
            self.assertEqual(notify.call_count, 1)
            self.assertIn("probleme", notify.call_args.args[1])
            asyncio.run(main.watchdog_after_cycle({"errors": []}))
            asyncio.run(main.watchdog_after_cycle({"errors": []}))
        self.assertEqual(notify.call_count, 2)
        self.assertIn("din nou", notify.call_args.args[1])

    def test_downtime_alert_after_a_long_gap_only(self):
        shop = main.default_shop()
        now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
        with patch.object(main, "notify_merchant_text", new_callable=AsyncMock) as notify:
            db.set_state(shop, "autopilot_last_cycle_at", (now - timedelta(minutes=20)).isoformat())
            self.assertIsNone(asyncio.run(main.check_downtime_on_start(now)))
            db.set_state(shop, "autopilot_last_cycle_at", (now - timedelta(hours=6)).isoformat())
            gap = asyncio.run(main.check_downtime_on_start(now))
        self.assertAlmostEqual(gap.total_seconds(), 6 * 3600)
        notify.assert_called_once()
        self.assertTrue(any("6.0 ore" in line for line in notify.call_args.args[2]))

    def test_alert_formats_escape_html(self):
        text = MobileNotifier().format_telegram_message("jarvis_alert", {"title": "<b>x</b>", "lines": ["a<script>"]})
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        embed = MobileNotifier().format_discord_embed("weekly_report", {"title": "Raport", "lines": ["1", "2"]})
        self.assertEqual(embed["description"], "1\n2")


class TestWeeklyReport(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.shop = f"r{uuid.uuid4().hex[:8]}.myshopify.com"

    def test_report_counts_only_real_events(self):
        now = datetime.now(timezone.utc)
        db.save_autopilot_log(self.shop, "autopilot_stage_1_recovery", "Ana", "a@x.com", "s", "m", status="stage_1_sent_email")
        db.save_autopilot_log(self.shop, "autopilot_stage_2_recovery", "Ana", "a@x.com", "s", "m", status="stage_2_failed")
        db.save_autopilot_log(self.shop, "vip_review_upsell", "Bo", "b@x.com", "s", "m", status="vip_sent_email")
        cid = uuid.uuid4().hex[:10]
        db.upsert_checkout_drip_state(self.shop, {"id": cid, "email": "a@x.com", "created_at": now.isoformat(),
                                                  "checkout_url": "https://x"})
        db.claim_drip_stage(cid, 0, 1)
        db.mark_drip_converted(self.shop, checkout_id=cid, order_id="1", revenue=120.5)
        db.record_opt_out(self.shop, email="gone@x.com")
        db.record_opt_out(self.shop, email="bounce@x.com", source="resend_bounce")
        data = main.build_weekly_report(self.shop)["data"]
        self.assertEqual(data["cart_messages_sent"], 1)
        self.assertEqual(data["cart_messages_failed"], 1)
        self.assertEqual(data["vip_thank_yous_sent"], 1)
        self.assertEqual(data["recovered_orders"], 1)
        self.assertAlmostEqual(data["recovered_revenue"], 120.5)
        self.assertEqual(data["opt_outs"], 2)
        self.assertEqual(data["bounces_and_complaints"], 1)

    def test_sent_on_monday_morning_once_per_week(self):
        monday_10 = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)   # 10:00 Madrid
        monday_8 = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)    # 07:00 Madrid
        tuesday = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
        with patch.object(main, "_alert_shop", return_value=self.shop), \
                patch.object(main, "notify_merchant_text", new_callable=AsyncMock) as notify:
            self.assertFalse(asyncio.run(main.maybe_send_weekly_report(monday_8)))
            self.assertFalse(asyncio.run(main.maybe_send_weekly_report(tuesday)))
            self.assertTrue(asyncio.run(main.maybe_send_weekly_report(monday_10)))
            self.assertFalse(asyncio.run(main.maybe_send_weekly_report(monday_10 + timedelta(hours=2))))
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(notify.call_args.kwargs.get("event"), "weekly_report")

    def test_report_endpoint_needs_auth(self):
        client = TestClient(main.app)
        self.assertEqual(client.get("/api/reports/weekly").status_code, 401)
        r = client.get("/api/reports/weekly?days=7", headers=AUTH_HEADERS)
        self.assertEqual(r.status_code, 200)
        self.assertIn("cart_messages_sent", r.json()["data"])


if __name__ == "__main__":
    unittest.main()

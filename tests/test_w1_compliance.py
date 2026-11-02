"""
W1 compliance & persistence regression suite (CONTRACT.md, EU / Spain LSSI + GDPR).

Covers every P0/P1 fixed by W1:
- consent unknown -> blocked; tri-state consent; email consent never authorizes WhatsApp
- opt-out always wins (also against automated re-syncs) and survives GDPR redaction (hashed suppression)
- phone / email normalization for consent, opt-out and frequency keys
- quiet hours 21:00-09:00 Europe/Madrid incl. DST switch dates
- frequency policy with sequence_key (cart 3 per checkout, VIP 1 per order, 4 / 30 days, 72h new-sequence rule)
- claim_drip_stage / release_drip_stage atomic compare-and-set (incl. a thread race)
- unsubscribe URL with the real email, List-Unsubscribe + List-Unsubscribe-Post headers, footer identity
- email dispatcher: Reply-To, Resend -> SMTP fallback, sender From, no double display-name, truthful results
- WhatsApp: consent gate, STOP line, wa.me link is not a send
- post-delivery VIP: per-channel compliance, suppressed when opted out, never review-conditioned discount
- database portability: JARVIS_SQLITE_PATH, commit errors raise, no silent SQLite fallback,
  portable is_checkout_recently_processed, pure-read get_shop, no placeholder seeds, GDPR export/redact/purge
No real network calls: httpx / smtplib are mocked everywhere.
"""

try:
    from tests import _test_env  # noqa: F401  (isolated SQLite file per test run)
except ImportError:  # pragma: no cover
    import _test_env  # noqa: F401

import os
import re
import sys
import shutil
import tempfile
import uuid
import sqlite3
import asyncio
import threading
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from tests import helpers  # noqa: F401  (puts backend/ on sys.path)

import database as db
import compliance_guard as cg
import email_dispatcher as ed
import whatsapp_dispatcher as wd
import post_delivery_service as pdsmod
from email_dispatcher import EmailDispatcher, EMAIL_I18N, build_unsubscribe_url, UNSUBSCRIBE_PLACEHOLDER
from whatsapp_dispatcher import WhatsAppDispatcher
from post_delivery_service import PostDeliveryService
from cadence_manager import DripCadenceManager
from mobile_notifier import MobileNotifier

# Daytime instant (14:00 Madrid in summer) for checks that are not about quiet hours.
DAY = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def new_shop() -> str:
    return f"w1-{uuid.uuid4().hex[:10]}.myshopify.com"


def run(coro):
    return asyncio.run(coro)


def setUpModule():
    db.init_db()


# ── Normalization ─────────────────────────────────────────────────────────────

class TestNormalization(unittest.TestCase):
    def test_normalize_email(self):
        self.assertEqual(db.normalize_email("  Ana.Lopez@Example.COM \n"), "ana.lopez@example.com")
        for empty in (None, "", "   "):
            self.assertIsNone(db.normalize_email(empty))

    def test_normalize_phone_equivalences(self):
        variants = ["+34 699 333 444", "34699333444", "0034 699-333-444", "(+34) 699.333.444", "699333444"]
        self.assertEqual({db.normalize_phone(v) for v in variants}, {"34699333444"})
        self.assertEqual(db.normalize_phone("+40 721 123 456"), db.normalize_phone("0721123456"))
        self.assertEqual(db.normalize_phone("+40 0722 123 456"), "40722123456")
        for empty in (None, "", "abc", "   "):
            self.assertIsNone(db.normalize_phone(empty))

    def test_whatsapp_destination_equals_consent_key(self):
        wa = WhatsAppDispatcher()
        for v in ["+34 699 333 444", "0722123456", "3401234567", "+49 151 12345678"]:
            self.assertEqual(wa.clean_phone_number(v), db.normalize_phone(v))


# ── Consent ───────────────────────────────────────────────────────────────────

class TestConsent(unittest.TestCase):
    def setUp(self):
        self.shop = new_shop()

    def test_unknown_consent_is_no_consent_and_blocks_dispatch(self):
        self.assertFalse(db.is_consent_given(self.shop, email="nobody@test.es"))
        self.assertFalse(db.is_consent_given(self.shop, phone="+34 600 000 001"))
        self.assertEqual(db.get_consent_status(self.shop, email="nobody@test.es"), db.CONSENT_UNKNOWN)
        ok, reason = cg.can_dispatch_to_customer(self.shop, email="nobody@test.es", channel="email", now_dt=DAY)
        self.assertFalse(ok)
        self.assertIn("No marketing consent", reason)
        ok, reason = cg.can_dispatch_to_customer(self.shop, phone="+34 600 000 001", channel="whatsapp", now_dt=DAY)
        self.assertFalse(ok)

    def test_tristate_none_writes_nothing(self):
        self.assertFalse(db.record_marketing_consent(self.shop, email="ana@test.es", accepts_marketing=None))
        self.assertEqual(db.get_consent_status(self.shop, email="ana@test.es"), db.CONSENT_UNKNOWN)
        self.assertTrue(db.record_marketing_consent(self.shop, email="ana@test.es", accepts_marketing=False))
        self.assertEqual(db.get_consent_status(self.shop, email="ana@test.es"), db.CONSENT_DENIED)
        self.assertTrue(db.record_marketing_consent(self.shop, email="ana@test.es", accepts_marketing=True))
        self.assertTrue(db.is_consent_given(self.shop, email="ana@test.es"))

    def test_email_consent_never_authorizes_whatsapp(self):
        db.record_marketing_consent(self.shop, email="luis@test.es", phone="+34 611 222 333", accepts_marketing=True)
        self.assertTrue(db.is_consent_given(self.shop, email="luis@test.es"))
        self.assertFalse(db.is_consent_given(self.shop, phone="+34 611 222 333", channel="whatsapp"))
        ok, reason = cg.can_dispatch_to_customer(
            self.shop, email="luis@test.es", phone="+34 611 222 333", channel="whatsapp", now_dt=DAY)
        self.assertFalse(ok)
        self.assertIn("whatsapp", reason)

    def test_phone_consent_keyed_by_normalized_phone(self):
        db.record_marketing_consent(self.shop, phone="+34 699 333 444", accepts_marketing=True, source="checkout")
        self.assertTrue(db.is_consent_given(self.shop, phone="0034699333444", channel="whatsapp"))
        self.assertTrue(db.is_consent_given(self.shop, phone="34699333444", channel="sms"))
        ok, _ = cg.can_dispatch_to_customer(self.shop, phone="699 333 444", channel="whatsapp", now_dt=DAY)
        self.assertTrue(ok)

    def test_email_consent_keyed_by_normalized_email(self):
        db.record_marketing_consent(self.shop, email="  Marta.G@Test.ES ", accepts_marketing=True)
        self.assertTrue(db.is_consent_given(self.shop, email="marta.g@test.es"))
        ok, _ = cg.can_dispatch_to_customer(self.shop, email="MARTA.G@TEST.ES", channel="email", now_dt=DAY)
        self.assertTrue(ok)

    def test_opt_out_wins_over_automated_resync(self):
        db.record_marketing_consent(self.shop, email="pia@test.es", accepts_marketing=True)
        self.assertTrue(db.record_opt_out(self.shop, email=" PIA@test.es"))
        self.assertEqual(db.get_consent_status(self.shop, email="pia@test.es"), db.CONSENT_OPTED_OUT)
        # The 15-minute checkout / order sync must not re-subscribe them
        self.assertFalse(db.record_marketing_consent(self.shop, email="pia@test.es", accepts_marketing=True, source="checkout"))
        self.assertFalse(db.record_marketing_consent(self.shop, email="pia@test.es", accepts_marketing=True, source="order"))
        self.assertFalse(db.is_consent_given(self.shop, email="pia@test.es"))
        ok, reason = cg.can_dispatch_to_customer(self.shop, email="pia@test.es", now_dt=DAY)
        self.assertFalse(ok)
        self.assertIn("opted out", reason.lower())
        # Only an explicit re-subscription lifts it
        self.assertTrue(db.record_marketing_consent(self.shop, email="pia@test.es", accepts_marketing=True, source="resubscribe"))
        self.assertTrue(db.is_consent_given(self.shop, email="pia@test.es"))

    def test_phone_opt_out_matches_any_format(self):
        db.record_marketing_consent(self.shop, phone="+34 655 444 333", accepts_marketing=True)
        db.record_opt_out(self.shop, phone="34655444333")
        self.assertFalse(db.is_consent_given(self.shop, phone="+34 655 444 333", channel="whatsapp"))
        self.assertTrue(db.is_suppressed(self.shop, phone="0034 655 444 333"))

    def test_consent_is_per_shop(self):
        other = new_shop()
        db.record_marketing_consent(self.shop, email="iso@test.es", accepts_marketing=True)
        self.assertFalse(db.is_consent_given(other, email="iso@test.es"))

    def test_legacy_rows_are_migrated_safely(self):
        """Pre-W1 rows mixed email+phone and default-True consent; init_db splits them."""
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, source, channel)
                               VALUES(%s, %s, %s, 1, 'checkout', NULL)""", (self.shop, "legacy@test.es", "+34 622 111 000"))
                cur.execute("""INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, opt_out_at, source, channel)
                               VALUES(%s, %s, NULL, 0, NOW(), 'unsubscribe_link', NULL)""", (self.shop, "gone@test.es"))
                cur.execute("""INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, source, channel)
                               VALUES(%s, NULL, %s, 1, 'checkout', NULL)""", (self.shop, "+34 633 999 888"))
            conn.commit()
        db.init_db()
        # The old code invented consent (default True), so a legacy grant becomes UNKNOWN (= no consent)
        self.assertFalse(db.is_consent_given(self.shop, email="legacy@test.es"))
        self.assertFalse(db.is_consent_given(self.shop, phone="+34 622 111 000", channel="whatsapp"))
        self.assertFalse(db.is_consent_given(self.shop, phone="+34 633 999 888", channel="whatsapp"))
        self.assertTrue(db.is_suppressed(self.shop, email="gone@test.es"))


# ── GDPR redaction / export / purge ──────────────────────────────────────────

class TestGDPR(unittest.TestCase):
    def setUp(self):
        self.shop = new_shop()
        self.email = "Elena.R@Test.ES"
        self.phone = "+34 644 555 666"

    def _seed_customer(self, shop, email, phone, cid, order_id):
        db.record_marketing_consent(shop, email=email, accepts_marketing=True)
        db.record_marketing_consent(shop, phone=phone, accepts_marketing=True)
        db.upsert_checkout_drip_state(shop, {"id": cid, "email": email, "phone": phone,
                                             "checkout_url": "https://x/checkouts/ac/1",
                                             "created_at": DAY.isoformat(), "customer_name": "Elena"})
        db.enqueue_post_delivery_automation(shop=shop, order_id=order_id, customer_email=email,
                                            customer_phone=phone, customer_name="Elena", fulfilled_at=DAY)
        db.save_autopilot_log(shop, "autopilot_stage_1_recovery", "Elena", email, "s", "m", checkout_id=cid)
        db.record_message_sent(shop, email, "email", "abandoned_cart_stage_1", sequence_key=f"cart:{cid}", sent_at=DAY)
        db.record_message_sent(shop, phone, "whatsapp", "abandoned_cart_stage_1", sequence_key=f"cart:{cid}", sent_at=DAY)
        db.save_message(shop, "user", f"Ce face clientul {email.lower()}?")

    def test_redaction_keeps_opted_out_customer_suppressed(self):
        cid, oid = f"c-{uuid.uuid4().hex[:8]}", f"o-{uuid.uuid4().hex[:8]}"
        self._seed_customer(self.shop, self.email, self.phone, cid, oid)
        db.record_opt_out(self.shop, email=self.email)

        res = db.redact_customer(self.shop, email=self.email, phone=self.phone, order_ids=[oid])
        self.assertTrue(res["ok"])
        self.assertTrue(res["suppression_kept"])
        for table in ("checkout_drip_states", "post_delivery_automations", "autopilot_logs",
                      "marketing_consents", "message_frequency_logs", "messages"):
            self.assertGreaterEqual(res["deleted"][table], 1, table)

        exported = db.export_customer_data(self.shop, email=self.email, phone=self.phone)
        self.assertTrue(all(len(rows) == 0 for rows in exported["data"].values()), exported["counts"])
        self.assertTrue(exported["suppressed"])
        # No plaintext email left in the suppression list, only the sha256
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT identifier_hash FROM suppression_list WHERE shop_domain = %s", (self.shop,))
                hashes = [r["identifier_hash"] for r in cur.fetchall()]
        self.assertIn(db.identity_hash("elena.r@test.es"), hashes)
        self.assertTrue(all("@" not in h for h in hashes))

        # After redaction an automated re-sync must not make them reachable again
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True, source="checkout")
        self.assertFalse(db.is_consent_given(self.shop, email=self.email))
        ok, reason = cg.can_dispatch_to_customer(self.shop, email=self.email, now_dt=DAY)
        self.assertFalse(ok)
        self.assertIn("opted out", reason.lower())

    def test_redaction_without_opt_out_leaves_no_suppression(self):
        cid, oid = f"c-{uuid.uuid4().hex[:8]}", f"o-{uuid.uuid4().hex[:8]}"
        self._seed_customer(self.shop, self.email, self.phone, cid, oid)
        res = db.redact_customer(self.shop, email=self.email, phone=self.phone)
        self.assertFalse(res["suppression_kept"])
        self.assertFalse(db.is_suppressed(self.shop, email=self.email, phone=self.phone))
        self.assertEqual(db.get_consent_status(self.shop, email=self.email), db.CONSENT_UNKNOWN)

    def test_redaction_and_export_are_scoped_to_shop_and_customer(self):
        other_shop = new_shop()
        self._seed_customer(self.shop, self.email, self.phone, f"c-{uuid.uuid4().hex[:8]}", f"o-{uuid.uuid4().hex[:8]}")
        self._seed_customer(other_shop, self.email, self.phone, f"c-{uuid.uuid4().hex[:8]}", f"o-{uuid.uuid4().hex[:8]}")
        self._seed_customer(self.shop, "other@test.es", "+34 600 111 222", f"c-{uuid.uuid4().hex[:8]}", f"o-{uuid.uuid4().hex[:8]}")

        exported = db.export_customer_data(self.shop, email=self.email)
        self.assertEqual(exported["counts"]["checkout_drip_states"], 1)
        self.assertEqual(exported["consent"]["email"], db.CONSENT_GRANTED)

        db.redact_customer(self.shop, email=self.email, phone=self.phone)
        self.assertTrue(db.is_consent_given(other_shop, email=self.email))
        self.assertTrue(db.is_consent_given(self.shop, email="other@test.es"))
        self.assertEqual(db.export_customer_data(other_shop, email=self.email)["counts"]["checkout_drip_states"], 1)

    def test_purge_shop_covers_every_table(self):
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                if isinstance(conn, db.SQLiteConnection):
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                    tables = {r["name"] for r in cur.fetchall()}
                else:  # pragma: no cover - PostgreSQL run
                    cur.execute("SELECT table_name AS name FROM information_schema.tables WHERE table_schema='public'")
                    tables = {r["name"] for r in cur.fetchall()}
        self.assertEqual(tables, {t for t, _ in db.SHOP_TABLES})

        self._seed_customer(self.shop, self.email, self.phone, f"c-{uuid.uuid4().hex[:8]}", f"o-{uuid.uuid4().hex[:8]}")
        db.record_opt_out(self.shop, email=self.email)
        db.upsert_shop(self.shop, "shpat_real_token_for_test", "Grozavu")
        db.save_shop_settings(self.shop, {"sender_name": "Grozavu"})
        db.save_briefing(self.shop, {"x": 1})
        db.store_nonce(self.shop, "n1")
        db.log_seo_change(self.shop, "1", "Hoodie", "title", "a", "b", status="proposed")
        keep = new_shop()
        db.record_marketing_consent(keep, email=self.email, accepts_marketing=True)

        res = db.purge_shop(self.shop)
        self.assertTrue(res["ok"])
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                for table, col in db.SHOP_TABLES:
                    cur.execute(f"SELECT COUNT(*) AS cnt FROM {table} WHERE {col} = %s", (self.shop,))
                    self.assertEqual(db._count(cur.fetchone()), 0, table)
        self.assertTrue(db.is_consent_given(keep, email=self.email))


# ── Quiet hours (Europe/Madrid, DST) ──────────────────────────────────────────

class TestQuietHoursMadrid(unittest.TestCase):
    def _q(self, y, mo, d, h, mi=0):
        return cg.is_quiet_hours(datetime(y, mo, d, h, mi, tzinfo=timezone.utc))

    def test_summer_cest_utc_plus_2(self):
        self.assertFalse(self._q(2026, 7, 15, 18, 59))  # 20:59 local
        self.assertTrue(self._q(2026, 7, 15, 19, 0))    # 21:00 local
        self.assertTrue(self._q(2026, 7, 15, 6, 59))    # 08:59 local
        self.assertFalse(self._q(2026, 7, 15, 7, 0))    # 09:00 local

    def test_winter_cet_utc_plus_1(self):
        self.assertFalse(self._q(2026, 1, 15, 19, 59))  # 20:59 local
        self.assertTrue(self._q(2026, 1, 15, 20, 0))    # 21:00 local
        self.assertTrue(self._q(2026, 1, 15, 7, 59))    # 08:59 local
        self.assertFalse(self._q(2026, 1, 15, 8, 0))    # 09:00 local

    def test_spring_forward_2026_03_29(self):
        self.assertTrue(self._q(2026, 3, 28, 7, 30))    # Sat 08:30 CET
        self.assertFalse(self._q(2026, 3, 28, 8, 0))    # Sat 09:00 CET
        self.assertTrue(self._q(2026, 3, 29, 6, 30))    # Sun 08:30 CEST
        self.assertFalse(self._q(2026, 3, 29, 7, 0))    # Sun 09:00 CEST

    def test_fall_back_2026_10_25(self):
        self.assertFalse(self._q(2026, 10, 24, 7, 0))   # Sat 09:00 CEST
        self.assertTrue(self._q(2026, 10, 25, 7, 30))   # Sun 08:30 CET
        self.assertFalse(self._q(2026, 10, 25, 8, 0))   # Sun 09:00 CET
        # Old fixed "UTC+2 Bucharest" logic said quiet here; Madrid is 20:00
        self.assertFalse(self._q(2026, 10, 28, 19, 0))
        self.assertTrue(self._q(2026, 10, 28, 20, 0))

    def test_naive_datetime_is_utc(self):
        self.assertTrue(cg.is_quiet_hours(datetime(2026, 7, 15, 19, 30)))
        self.assertFalse(cg.is_quiet_hours(datetime(2026, 7, 15, 12, 0)))

    def test_fallback_without_tzdata_matches_zoneinfo(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Madrid")
        t = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
        while t.year == 2026:
            self.assertEqual(cg._madrid_local_fallback(t).hour, t.astimezone(tz).hour, t.isoformat())
            t += timedelta(hours=7)

    def test_labels_and_policy_for_dashboard(self):
        self.assertIn("21:00", cg.QUIET_HOURS_LABEL)
        self.assertIn("09:00", cg.QUIET_HOURS_LABEL)
        self.assertEqual(cg.FREQUENCY_POLICY["cart_max_per_checkout"], 3)
        self.assertEqual(cg.FREQUENCY_POLICY["vip_max_per_order"], 1)
        self.assertEqual(cg.FREQUENCY_POLICY["max_marketing_per_30d"], 4)
        self.assertEqual(cg.FREQUENCY_POLICY["new_sequence_cooldown_hours"], 72)
        self.assertEqual(cg.FREQUENCY_POLICY["quiet_hours_timezone"], "Europe/Madrid")

    def test_dispatch_blocked_in_quiet_hours_even_with_consent(self):
        shop = new_shop()
        db.record_marketing_consent(shop, email="night@test.es", accepts_marketing=True)
        night = datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc)  # 23:00 Madrid
        ok, reason = cg.can_dispatch_to_customer(shop, email="night@test.es", now_dt=night)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("Quiet hours"))
        self.assertTrue(cg.is_transient_block(reason))
        ok, _ = cg.can_dispatch_to_customer(shop, email="night@test.es", now_dt=night, bypass_quiet_hours=True)
        self.assertTrue(ok)


# ── Frequency policy with sequence_key ───────────────────────────────────────

class TestFrequencyPolicy(unittest.TestCase):
    def setUp(self):
        self.shop = new_shop()
        self.email = "freq@test.es"
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True)

    def _can(self, key, at, message_type="marketing", phone=None, channel="email"):
        return cg.can_dispatch_to_customer(self.shop, email=self.email, phone=phone, channel=channel, now_dt=at,
                                           sequence_key=key, message_type=message_type)

    def _log(self, key, at, recipient=None, message_type=None, channel="email"):
        # each logged message is a distinct step unless a message_type is given
        self._step = getattr(self, "_step", 0) + 1
        cg.log_customer_dispatch(self.shop, recipient or self.email, channel, message_type or f"marketing_step_{self._step}",
                                 sequence_key=key, sent_at=at)

    def test_cart_stages_2_and_3_not_blocked_by_72h_rule_but_capped_at_3(self):
        t0 = DAY
        key = "cart:ch_1001"
        self.assertTrue(self._can(key, t0)[0])
        self._log(key, t0)
        self.assertTrue(self._can(key, t0 + timedelta(hours=4))[0], "stage 2 must not be blocked")
        self._log(key, t0 + timedelta(hours=4))
        self.assertTrue(self._can(key, t0 + timedelta(hours=24))[0], "stage 3 must not be blocked")
        self._log(key, t0 + timedelta(hours=24))
        ok, reason = self._can(key, t0 + timedelta(hours=25))
        self.assertFalse(ok)
        self.assertIn("sequence", reason)
        self.assertFalse(cg.is_transient_block(reason))

    def test_new_sequence_blocked_within_72h(self):
        self._log("cart:A", DAY)
        ok, reason = self._can("cart:B", DAY + timedelta(hours=5))
        self.assertFalse(ok)
        self.assertIn("72 hours", reason)
        self.assertTrue(cg.is_transient_block(reason))
        ok, reason = self._can("vip:ord_1", DAY + timedelta(hours=48))
        self.assertFalse(ok)
        self.assertTrue(self._can("cart:B", DAY + timedelta(hours=73))[0])

    def test_vip_max_one_per_order(self):
        self._log("vip:ord_9", DAY)
        ok, reason = self._can("vip:ord_9", DAY + timedelta(days=10))
        self.assertFalse(ok)
        self.assertFalse(cg.is_transient_block(reason))
        self.assertTrue(self._can("vip:ord_10", DAY + timedelta(days=10))[0])

    def test_max_four_per_rolling_30_days(self):
        for i in range(4):
            self._log(f"cart:s{i}", DAY + timedelta(days=4 * i))
        ok, reason = self._can("cart:s5", DAY + timedelta(days=16))
        self.assertFalse(ok)
        self.assertIn("30 days", reason)
        self.assertTrue(self._can("cart:s5", DAY + timedelta(days=31))[0])

    def test_followups_count_toward_30_day_cap(self):
        self._log("vip:ord_1", DAY - timedelta(days=10))
        self._log("cart:old", DAY - timedelta(days=6))
        self._log("cart:X", DAY)
        self._log("cart:X", DAY + timedelta(hours=4))
        ok, reason = self._can("cart:X", DAY + timedelta(hours=24))
        self.assertFalse(ok)
        self.assertIn("30 days", reason)

    def test_unkeyed_message_keeps_legacy_one_per_72h(self):
        self._log(None, DAY)
        ok, reason = self._can(None, DAY + timedelta(hours=1))
        self.assertFalse(ok)
        self.assertIn("Frequency cap", reason)

    def test_recipient_normalized_in_frequency_log(self):
        self._log("cart:N", DAY, recipient="  FREQ@Test.ES ")
        ok, _ = self._can("cart:M", DAY + timedelta(hours=2))
        self.assertFalse(ok)
        shop = new_shop()
        db.record_marketing_consent(shop, phone="+34 677 888 999", accepts_marketing=True)
        cg.log_customer_dispatch(shop, "0034 677-888-999", "whatsapp", "marketing", sequence_key="cart:P", sent_at=DAY)
        ok, _ = cg.can_dispatch_to_customer(shop, phone="34677888999", channel="whatsapp",
                                            now_dt=DAY + timedelta(hours=2), sequence_key="cart:Q")
        self.assertFalse(ok)

    def test_caps_count_per_person_across_email_and_whatsapp(self):
        phone = "+34 699 123 456"
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True)
        db.record_marketing_consent(self.shop, phone=phone, accepts_marketing=True)
        # WhatsApp message of a cart sequence blocks a NEW email sequence within 72h for the same person
        self._log("cart:WA1", DAY, recipient=phone, message_type="abandoned_cart_stage_1", channel="whatsapp")
        ok, reason = self._can("vip:ord_9", DAY + timedelta(hours=5), phone=phone)
        self.assertFalse(ok)
        self.assertIn("72 hours", reason)

    def test_same_step_on_two_channels_is_one_touch(self):
        phone = "+34 699 765 432"
        db.record_marketing_consent(self.shop, phone=phone, accepts_marketing=True)
        self._log("vip:o1", DAY - timedelta(days=20), message_type="vip_post_delivery")
        self._log("cart:a", DAY - timedelta(days=10), message_type="abandoned_cart_stage_1")
        self._log("cart:a", DAY - timedelta(days=10) + timedelta(hours=4), message_type="abandoned_cart_stage_2")
        self._log("cart:b", DAY, message_type="abandoned_cart_stage_1")  # 4th touch, by email
        # The same step by WhatsApp is not a 5th touch
        ok, reason = self._can("cart:b", DAY + timedelta(minutes=1), message_type="abandoned_cart_stage_1",
                               phone=phone, channel="whatsapp")
        self.assertTrue(ok, reason)
        # The next step would be a 5th touch -> blocked
        ok, reason = self._can("cart:b", DAY + timedelta(hours=4), message_type="abandoned_cart_stage_2")
        self.assertFalse(ok)
        self.assertIn("30 days", reason)

    def test_transactional_skips_consent_and_frequency(self):
        ok, _ = cg.can_dispatch_to_customer(self.shop, email="noconsent@test.es", now_dt=DAY,
                                            message_type="transactional")
        self.assertTrue(ok)


# ── claim / release drip stage ───────────────────────────────────────────────

class TestClaimReleaseDripStage(unittest.TestCase):
    def setUp(self):
        self.shop = new_shop()
        self.cid = f"ch_{uuid.uuid4().hex[:10]}"
        db.upsert_checkout_drip_state(self.shop, {"id": self.cid, "email": "c@test.es",
                                                  "checkout_url": "https://x/checkouts/ac/1",
                                                  "created_at": DAY.isoformat()})

    def test_compare_and_set_and_release(self):
        self.assertTrue(db.claim_drip_stage(self.cid, 0, 1))
        self.assertFalse(db.claim_drip_stage(self.cid, 0, 1), "second claimer must lose")
        st = db.get_checkout_drip_state(self.shop, self.cid)
        self.assertEqual(int(st["current_stage"]), 1)
        self.assertIsNotNone(st["stage_1_sent_at"])
        self.assertTrue(db.claim_drip_stage(self.cid, 1, 2))
        self.assertTrue(db.release_drip_stage(self.cid, 2, 1))
        st = db.get_checkout_drip_state(self.shop, self.cid)
        self.assertEqual(int(st["current_stage"]), 1)
        self.assertIsNone(st["stage_2_sent_at"])
        self.assertFalse(db.release_drip_stage(self.cid, 2, 1), "nothing left to release")

    def test_claim_refused_on_converted_checkout(self):
        db.mark_drip_converted(self.shop, checkout_id=self.cid, order_id="o1", revenue=10)
        self.assertFalse(db.claim_drip_stage(self.cid, 0, 1))

    def test_invalid_stages_rejected(self):
        for exp, new in ((0, 4), (1, 1), (2, 1), (0, "1; DROP TABLE x")):
            with self.assertRaises(ValueError):
                db.claim_drip_stage(self.cid, exp, new)

    def test_thread_race_single_winner(self):
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(db.claim_drip_stage(self.cid, 0, 1))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 1, results)

    def test_update_drip_stage_never_clobbers_converted(self):
        db.mark_drip_converted(self.shop, checkout_id=self.cid, order_id="o1", revenue=10)
        self.assertFalse(db.update_drip_stage(self.cid, 3))
        self.assertEqual(db.get_checkout_drip_state(self.shop, self.cid)["status"], "converted")

    def test_recovered_revenue_only_credited_when_a_stage_was_sent(self):
        cadence = DripCadenceManager()
        res = cadence.reconcile_order(self.shop, {"id": 1, "checkout_id": self.cid, "total_price": "50.00"})
        self.assertEqual(res, {"converted": 1, "attributed": False})
        self.assertEqual(float(db.get_checkout_drip_state(self.shop, self.cid)["revenue_recovered"] or 0), 0.0)

        cid2 = f"ch_{uuid.uuid4().hex[:10]}"
        db.upsert_checkout_drip_state(self.shop, {"id": cid2, "email": "d@test.es",
                                                  "checkout_url": "https://x/c", "created_at": DAY.isoformat()})
        self.assertTrue(db.claim_drip_stage(cid2, 0, 1))
        res = cadence.reconcile_order(self.shop, {"id": 2, "checkout_id": cid2, "total_price": "80.00"})
        self.assertEqual(res, {"converted": 1, "attributed": True})
        self.assertEqual(float(db.get_checkout_drip_state(self.shop, cid2)["revenue_recovered"]), 80.0)

    def test_conversion_matches_unnormalized_email(self):
        cid = f"ch_{uuid.uuid4().hex[:10]}"
        db.upsert_checkout_drip_state(self.shop, {"id": cid, "email": "  Mixed.Case@Test.ES ",
                                                  "checkout_url": "https://x/c", "created_at": DAY.isoformat()})
        with db.get_conn() as conn:  # simulate a legacy row stored before normalization
            with conn.cursor() as cur:
                cur.execute("UPDATE checkout_drip_states SET email = %s WHERE checkout_id = %s",
                            ("  Mixed.Case@Test.ES ", cid))
            conn.commit()
        converted = DripCadenceManager().mark_order_converted(
            self.shop, {"id": 77, "email": "mixed.case@test.es ", "total_price": "free"})
        self.assertTrue(converted)
        self.assertEqual(db.get_checkout_drip_state(self.shop, cid)["status"], "converted")


# ── Email: unsubscribe, headers, footer, providers ───────────────────────────

class TestEmailCompliance(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"APP_URL": "https://jarvis.example-app.com",
                                           "SENDER_EMAIL": "Maison Grozavu <contact@maisongrozavu.com>",
                                           "RESEND_API_KEY": "", "SMTP_HOST": "", "SMTP_USER": "",
                                           "SMTP_PASSWORD": ""}, clear=False)
        self.env.start()
        os.environ.pop("REPLY_TO_EMAIL", None)
        self.addCleanup(self.env.stop)
        self.dispatcher = EmailDispatcher()

    def test_unsubscribe_url_contains_real_email_and_shop(self):
        url = build_unsubscribe_url("maisongrozavu.myshopify.com", "  Ana+Promo@Test.ES ")
        self.assertTrue(url.startswith("https://jarvis.example-app.com/api/unsubscribe?"))
        self.assertIn("email=ana%2Bpromo%40test.es", url)
        self.assertIn("shop=maisongrozavu.myshopify.com", url)
        with patch.dict(os.environ, {"APP_URL": "", "RENDER_EXTERNAL_URL": ""}):
            self.assertTrue(build_unsubscribe_url("s.myshopify.com", "a@b.es").startswith(
                "https://shopify-jarvis.onrender.com/api/unsubscribe?"))

    def test_footer_identifies_sender_marks_commercial_and_links_unsubscribe(self):
        expected = {"es": ("Publicidad", "Darse de baja"), "ro": ("Comunicare comercială", "Dezabonare"),
                    "en": ("Marketing communication", "Unsubscribe"), "it": ("Comunicazione commerciale", "Annulla"),
                    "fr": ("Communication commerciale", "Se désabonner"), "de": ("Werbung", "Abmelden")}
        for lang, (label, unsub) in expected.items():
            h = EmailDispatcher.build_html_email(shop_name="Grozavu", text_body="x", lang=lang,
                                                 customer_email="ana@test.es", shop_domain="maisongrozavu.myshopify.com")
            self.assertIn(label, h, lang)
            self.assertIn(unsub, h, lang)
            self.assertIn("© Grozavu · maisongrozavu.com", h, lang)
            self.assertIn("email=ana%40test.es", h, lang)
            self.assertNotIn(UNSUBSCRIBE_PLACEHOLDER, h)
        internal = EmailDispatcher.build_html_email(shop_name="Grozavu", text_body="x", lang="es", is_internal=True)
        self.assertNotIn("Publicidad", internal)
        self.assertNotIn("Darse de baja", internal)

    def test_no_fabricated_claims_in_templates(self):
        blob = " ".join(v for labels in EMAIL_I18N.values() for v in labels.values()).lower()
        for banned in ("reserv", "rezerv", "riserv", "priority", "prioritar", "prioritaire", "prioritär", "256-bit"):
            self.assertNotIn(banned, blob)
        self.assertNotIn("Release", DripCadenceManager().get_stage_metadata(3)["label"])

    def _resend_ok(self):
        resp = MagicMock(status_code=200, text="{}")
        resp.json.return_value = {"id": "re_123"}
        return resp

    async def test_customer_email_has_list_unsubscribe_headers_and_real_link(self):
        html_body = EmailDispatcher.build_html_email(shop_name="Grozavu", text_body="Hola", lang="es")
        self.assertIn(UNSUBSCRIBE_PLACEHOLDER, html_body)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=self._resend_ok()) as mock_post:
            res = await self.dispatcher.send_email(
                to_email="Cliente@Test.ES", subject="Hola", body_text="Hola", body_html=html_body,
                settings={"resend_api_key": "re_key", "shop": "maisongrozavu.myshopify.com"})
        self.assertTrue(res["success"])
        self.assertEqual(res["provider"], "resend")
        self.assertIsInstance(res["reason"], str)
        payload = mock_post.call_args[1]["json"]
        url = build_unsubscribe_url("maisongrozavu.myshopify.com", "cliente@test.es")
        self.assertEqual(payload["headers"]["List-Unsubscribe"], f"<{url}>")
        self.assertEqual(payload["headers"]["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIn(url.replace("&", "&amp;"), payload["html"])
        self.assertNotIn(UNSUBSCRIBE_PLACEHOLDER, payload["html"])
        self.assertIn(url, payload["text"])
        # SENDER_EMAIL already carries a display name -> no "Grozavu <Maison Grozavu <...>>"
        self.assertEqual(payload["from"], "Maison Grozavu <contact@maisongrozavu.com>")
        self.assertNotIn("reply_to", payload)

    async def test_reply_to_from_env_and_internal_email_has_no_unsubscribe(self):
        with patch.dict(os.environ, {"REPLY_TO_EMAIL": "info@maisongrozavu.com"}):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=self._resend_ok()) as mock_post:
                res = await self.dispatcher.send_email(
                    to_email="owner@test.es", subject="Alert", body_text="x",
                    settings={"resend_api_key": "re_key"}, is_internal=True)
        self.assertTrue(res["success"])
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["reply_to"], "info@maisongrozavu.com")
        self.assertNotIn("headers", payload)

    async def test_placeholder_sender_setting_does_not_override_env_sender(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=self._resend_ok()) as mock_post:
            await self.dispatcher.send_email(
                to_email="c@test.es", subject="s", body_text="b",
                settings={"resend_api_key": "k", "sender_email": "onboarding@resend.dev", "sender_name": "Grozavu"})
        self.assertEqual(mock_post.call_args[1]["json"]["from"], "Maison Grozavu <contact@maisongrozavu.com>")

    async def test_resend_error_falls_back_to_smtp_with_sender_from(self):
        err = MagicMock(status_code=422, text='{"message":"domain not verified"}')
        smtp_instance = MagicMock()
        settings = {"resend_api_key": "re_key", "smtp_host": "smtp.example-mail.com", "smtp_port": 587,
                    "smtp_user": "apikey", "smtp_password": "secret", "shop": "maisongrozavu.myshopify.com"}
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=err):
            with patch.object(ed.smtplib, "SMTP", return_value=smtp_instance) as smtp_cls:
                res = await self.dispatcher.send_email(to_email="c@test.es", subject="Hola",
                                                       body_text="Hola", settings=settings)
        self.assertTrue(res["success"])
        self.assertEqual(res["provider"], "smtp")
        self.assertIn("422", res["resend_error"])
        smtp_cls.assert_called_once()
        from_addr, to_addrs, raw = smtp_instance.sendmail.call_args[0]
        self.assertEqual(from_addr, "contact@maisongrozavu.com")
        self.assertEqual(to_addrs, ["c@test.es"])
        self.assertIn("From: Maison Grozavu <contact@maisongrozavu.com>", raw)
        self.assertNotIn("From: apikey", raw)
        self.assertIn("List-Unsubscribe-Post: List-Unsubscribe=One-Click", raw)

    async def test_resend_error_without_smtp_reports_failure(self):
        err = MagicMock(status_code=500, text="boom")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=err):
            res = await self.dispatcher.send_email(to_email="c@test.es", subject="s", body_text="b",
                                                   settings={"resend_api_key": "k"})
        self.assertIs(res["success"], False)
        self.assertIn("500", res["reason"])
        res = await self.dispatcher.send_email(to_email="c@test.es", subject="s", body_text="b", settings={})
        self.assertIs(res["success"], False)
        self.assertEqual(res["provider"], "none")
        self.assertTrue(res["reason"])


# ── WhatsApp: consent gate, STOP line, wa.me is not a send ───────────────────

class TestWhatsAppCompliance(unittest.TestCase):
    def setUp(self):
        self.shop = new_shop()
        self.wa = WhatsAppDispatcher()
        self.meta = {"shop": self.shop, "whatsapp_provider": "meta",
                     "whatsapp_api_token": "EAAX_test", "whatsapp_phone_number_id": "123"}

    def _meta_ok(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"messages": [{"id": "wamid.1"}]}
        return resp

    def test_marketing_without_phone_consent_is_blocked_without_network(self):
        db.record_marketing_consent(self.shop, email="x@test.es", accepts_marketing=True)  # email only
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = run(self.wa.send_message("+34 699 000 111", "Hola", settings=self.meta))
        mock_post.assert_not_called()
        self.assertIs(res["success"], False)
        self.assertEqual(res["status"], "blocked_no_consent")
        self.assertIsNone(res["wa_me_url"])

    def test_marketing_with_consent_appends_localized_stop_line(self):
        db.record_marketing_consent(self.shop, phone="+34 699 000 222", accepts_marketing=True)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=self._meta_ok()) as mock_post:
            res = run(self.wa.send_message("0034 699 000 222", "Hola Ana", settings=self.meta))
        self.assertIs(res["success"], True)
        self.assertEqual(res["status"], "sent")
        body = mock_post.call_args[1]["json"]["text"]["body"]
        self.assertTrue(body.startswith("Hola Ana"))
        # No inbound WhatsApp webhook exists, so the opt-out is a working link, not a "reply STOP" promise
        self.assertIn("Para no recibir más mensajes: ", body)
        self.assertIn("/api/unsubscribe?phone=", body)
        self.assertNotIn("STOP", body)
        self.assertTrue(WhatsAppDispatcher.opt_out_line("ro").startswith("Ca să nu mai primești mesaje: "))
        self.assertIn("phone=447700", WhatsAppDispatcher.opt_out_line(None, "447700"))
        self.assertTrue(WhatsAppDispatcher.opt_out_line(None, "447700").startswith("To stop these messages: "))

    def test_opted_out_phone_is_blocked(self):
        db.record_marketing_consent(self.shop, phone="+34 699 000 333", accepts_marketing=True)
        db.record_opt_out(self.shop, phone="34699000333")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            res = run(self.wa.send_message("+34 699 000 333", "Hola", settings=self.meta))
        mock_post.assert_not_called()
        self.assertIs(res["success"], False)

    def test_wa_me_link_is_not_reported_as_sent(self):
        db.record_marketing_consent(self.shop, phone="+34 699 000 444", accepts_marketing=True)
        res = run(self.wa.send_message("+34 699 000 444", "Hola", settings={"shop": self.shop, "whatsapp_provider": "auto",
                                                                              "whatsapp_api_token": "", "twilio_account_sid": "",
                                                                              "whatsapp_webhook_url": ""}))
        self.assertIs(res["success"], False)
        self.assertIs(res["ok"], False)
        self.assertEqual(res["status"], "manual_link")
        self.assertTrue(res["wa_me_url"].startswith("https://wa.me/34699000444?text="))
        self.assertTrue(res["reason"])

    def test_provider_error_reports_failure(self):
        db.record_marketing_consent(self.shop, phone="+34 699 000 555", accepts_marketing=True)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=MagicMock(status_code=400, text="131047")):
            res = run(self.wa.send_message("+34 699 000 555", "Hola", settings=self.meta))
        self.assertIs(res["success"], False)
        self.assertEqual(res["status"], "failed")
        self.assertIn("131047", res["reason"])


# ── Post-delivery VIP ─────────────────────────────────────────────────────────

class TestVIPCompliance(unittest.TestCase):
    def setUp(self):
        self.shop = new_shop()
        self.service = PostDeliveryService()
        self.now = DAY
        self.oid = f"ord_{uuid.uuid4().hex[:10]}"
        self.email = f"vip_{uuid.uuid4().hex[:6]}@test.es"
        self.phone = "+34 688 " + str(uuid.uuid4().int)[:3] + " " + str(uuid.uuid4().int)[:3]
        db.enqueue_post_delivery_automation(
            shop=self.shop, order_id=self.oid, order_number="1001", customer_email=self.email,
            customer_phone=self.phone, customer_name="Lucía", fulfilled_at=self.now - timedelta(days=6),
            items_summary=[{"title": "Boxy Tee"}])
        self.mail = patch.object(self.service.email_dispatcher, "send_email", new_callable=AsyncMock,
                                 return_value={"success": True, "reason": "sent", "provider": "resend"})
        self.wa = patch.object(self.service.wa_dispatcher, "send_message", new_callable=AsyncMock,
                               return_value={"success": True, "status": "sent", "reason": "sent", "provider": "meta"})
        self.notify = patch.object(self.service.mobile_notifier, "notify_merchant", new_callable=AsyncMock)
        self.mock_mail = self.mail.start()
        self.mock_wa = self.wa.start()
        self.notify.start()
        for p in (self.mail, self.wa, self.notify):
            self.addCleanup(p.stop)

    def _status(self):
        return db.get_post_delivery_automation(self.oid)["status"]

    def test_vip_blocked_and_suppressed_when_opted_out(self):
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True)
        db.record_marketing_consent(self.shop, phone=self.phone, accepts_marketing=True)
        db.record_opt_out(self.shop, email=self.email, phone=self.phone)
        count = self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now)
        self.assertEqual(count, 0)
        self.mock_mail.assert_not_called()
        self.mock_wa.assert_not_called()
        self.assertEqual(self._status(), "suppressed")

    def test_vip_without_consent_sends_nothing(self):
        count = self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now)
        self.assertEqual(count, 0)
        self.mock_mail.assert_not_called()
        self.mock_wa.assert_not_called()
        self.assertEqual(self._status(), "suppressed")

    def test_vip_email_consent_only_sends_email_only_and_logs(self):
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True)
        count = self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now)
        self.assertEqual(count, 1)
        self.mock_mail.assert_called_once()
        self.mock_wa.assert_not_called()
        kwargs = self.mock_mail.call_args[1]
        self.assertEqual(kwargs["shop_domain"], self.shop)
        self.assertIn(f"email={self.email.replace('@', '%40')}", kwargs["body_html"])
        self.assertEqual(self._status(), "sent")
        counts = db.get_message_counts(self.shop, self.email, "email", sequence_key=f"vip:{self.oid}", now_dt=self.now)
        self.assertEqual(counts["sequence_total"], 1)

    def test_vip_whatsapp_uses_phone_consent(self):
        db.record_marketing_consent(self.shop, phone=self.phone, accepts_marketing=True)
        count = self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now)
        self.assertEqual(count, 1)
        self.mock_mail.assert_not_called()
        self.mock_wa.assert_called_once()
        self.assertEqual(self.mock_wa.call_args[1]["message_type"], "marketing")

    def test_vip_held_in_quiet_hours_then_sent(self):
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True)
        night = datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=night), 0)
        self.assertEqual(self._status(), "pending")
        self.mock_mail.assert_not_called()
        self.assertEqual(self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now + timedelta(days=1)), 1)

    def test_vip_held_by_72h_rule_after_cart_message(self):
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True)
        cg.log_customer_dispatch(self.shop, self.email, "email", "abandoned_cart_stage_1",
                                 sequence_key="cart:abc", sent_at=self.now - timedelta(hours=10))
        self.assertEqual(self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now), 0)
        self.assertEqual(self._status(), "pending")
        self.assertEqual(self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now + timedelta(days=3)), 1)

    def test_vip_failed_send_is_not_reported_as_sent(self):
        db.record_marketing_consent(self.shop, email=self.email, accepts_marketing=True)
        self.mock_mail.return_value = {"success": False, "reason": "Resend HTTP 500", "provider": "resend"}
        self.assertEqual(self.service.process_due_vip_automations(self.shop, {"shop": self.shop}, now_dt=self.now), 0)
        self.assertEqual(self._status(), "pending")
        self.assertEqual(db.get_message_counts(self.shop, self.email, "email", now_dt=self.now)["last_30d"], 0)

    def test_sync_never_invents_consent(self):
        orders = [
            {"id": 1, "email": "unknown@test.es", "fulfillments": [{"created_at": DAY.isoformat(), "status": "success"}]},
            {"id": 2, "email": "yes@test.es", "buyer_accepts_marketing": True,
             "fulfillments": [{"created_at": DAY.isoformat(), "status": "success"}]},
            {"id": 3, "email": "state@test.es", "phone": "+34 600 123 999",
             "customer": {"email_marketing_consent": {"state": "subscribed"},
                          "sms_marketing_consent": {"state": "not_subscribed"}},
             "fulfillments": [{"created_at": DAY.isoformat(), "status": "success"}]},
        ]
        client = MagicMock()
        client.get_recent_orders = AsyncMock(return_value=orders)
        with patch.object(pdsmod, "ShopifyClient", return_value=client):
            with patch.object(pdsmod.db, "get_shop", return_value={"shop": self.shop, "access_token": "t"}):
                with patch.object(pdsmod.db, "enqueue_post_delivery_automation", return_value=True):
                    self.service.sync_fulfilled_orders(self.shop)
        self.assertEqual(db.get_consent_status(self.shop, email="unknown@test.es"), db.CONSENT_UNKNOWN)
        self.assertTrue(db.is_consent_given(self.shop, email="yes@test.es"))
        self.assertTrue(db.is_consent_given(self.shop, email="state@test.es"))
        self.assertEqual(db.get_consent_status(self.shop, phone="+34 600 123 999", channel="sms"), db.CONSENT_DENIED)

    def test_vip_copy_never_conditions_discount_on_review(self):
        banned = re.compile(r"5[\s-]*(star|stern|estrell|stell|stel|étoil)|if you leave|si nos dejas|leave an honest review and|"
                            r"hinterlasse|laissez-nous un avis", re.I)
        optional = {"en": "optional", "es": "opcional", "ro": "opțional", "it": "facoltativ", "de": "freiwillig", "fr": "facultatif"}
        for lang in ["en", "es", "ro", "it", "de", "fr"]:
            msg = PostDeliveryService.build_vip_message("Ana", "Hoodie", discount_code="MGVIP15", lang=lang, shop_name="Grozavu")
            subj = PostDeliveryService.build_vip_subject("Ana", "MGVIP15", lang)
            self.assertIsNone(banned.search(msg), f"{lang}: {msg}")
            self.assertIsNone(banned.search(subj), f"{lang}: {subj}")
            self.assertIn("Grozavu", msg)
            self.assertIn("MGVIP15", msg)
            self.assertIn("15%", msg)
            self.assertIn(optional[lang], msg)
            # The code (thank-you) comes before, and independent of, the review sentence
            self.assertLess(msg.index("MGVIP15"), msg.lower().index(optional[lang]))
            self.assertNotIn("Client", PostDeliveryService.build_vip_message("", "Hoodie", lang=lang))


# ── Database portability & safety ────────────────────────────────────────────

class TestDatabaseSafety(unittest.TestCase):
    def test_sqlite_path_from_env(self):
        tmp = tempfile.mkdtemp(prefix="w1_sqlite_")
        self.addCleanup(shutil.rmtree, tmp, True)
        alt_path = os.path.join(tmp, "nested", "w1_alt.db")
        with patch.dict(os.environ, {"JARVIS_SQLITE_PATH": alt_path}):
            alt = db.SQLiteConnection()
            self.assertEqual(alt.db_path, alt_path)
            alt.close()
        self.assertTrue(os.path.exists(alt_path))

    def test_commit_errors_are_raised_not_swallowed(self):
        tmp = tempfile.mkdtemp(prefix="w1_sqlite_")
        self.addCleanup(shutil.rmtree, tmp, True)
        conn = db.SQLiteConnection(os.path.join(tmp, "commit.db"))
        conn.conn = MagicMock()
        conn.conn.commit.side_effect = sqlite3.OperationalError("disk I/O error")
        with self.assertRaises(sqlite3.OperationalError):
            conn.commit()
        with self.assertRaises(sqlite3.OperationalError):
            with conn:
                pass

    def test_no_silent_sqlite_fallback_when_postgres_configured(self):
        with patch.object(db, "DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x"):
            with patch.object(db.psycopg2, "connect", side_effect=db.psycopg2.OperationalError("refused")):
                with self.assertRaises(db.DatabaseUnavailableError):
                    db.get_conn()
                with self.assertRaises(db.DatabaseUnavailableError):
                    db.save_autopilot_log("s.myshopify.com", "a", "n", "e", "s", "m")

    def test_is_checkout_recently_processed_portable(self):
        shop = new_shop()
        self.assertFalse(db.is_checkout_recently_processed(shop, checkout_id="ch_x"))
        db.save_autopilot_log(shop, "autopilot_stage_1_recovery", "Ana", " Ana@Test.es", "s", "m", checkout_id="ch_x")
        self.assertTrue(db.is_checkout_recently_processed(shop, checkout_id="ch_x", hours=48))
        self.assertTrue(db.is_checkout_recently_processed(shop, email="ana@test.es", hours=48))
        self.assertFalse(db.is_checkout_recently_processed(
            shop, checkout_id="ch_x", hours=1, now_dt=datetime.now(timezone.utc) + timedelta(hours=5)))

    def test_get_shop_is_pure_read_and_no_placeholder_seed(self):
        shop = new_shop()
        self.assertIsNone(db.get_shop(shop))
        self.assertIsNone(db.get_shop("  " + shop.upper()))
        self.assertIsNone(db.get_shop("maisongrozavu-" + uuid.uuid4().hex[:6] + ".myshopify.com"))
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM shops WHERE shop = %s", (shop,))
                self.assertEqual(db._count(cur.fetchone()), 0)
        db.upsert_shop(shop.upper(), "shpat_real", "Grozavu")
        self.assertEqual(db.get_shop(shop)["shop_name"], "Grozavu")

    def test_init_db_on_fresh_database_seeds_nothing(self):
        if db.DATABASE_URL:  # pragma: no cover - only meaningful for SQLite runs
            self.skipTest("fresh-database check runs on SQLite")
        base_dir = os.path.dirname(os.path.abspath(os.environ.get("JARVIS_SQLITE_PATH") or db.SQLITE_PATH))
        fresh = os.path.join(base_dir, f"w1_fresh_{uuid.uuid4().hex[:8]}.db")
        try:
            with patch.dict(os.environ, {"JARVIS_SQLITE_PATH": fresh}):
                db.init_db()
                db.init_db()  # idempotent
                with db.get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) AS cnt FROM shops")
                        self.assertEqual(db._count(cur.fetchone()), 0)
                        cur.execute("SELECT COUNT(*) AS cnt FROM shop_settings")
                        self.assertEqual(db._count(cur.fetchone()), 0)
        finally:
            if os.path.exists(fresh):
                os.remove(fresh)

    def test_shop_settings_defaults_come_from_env(self):
        with patch.dict(os.environ, {"MERCHANT_NOTIFY_EMAIL": "owner@test.es"}):
            s = db.get_shop_settings(new_shop())
        self.assertEqual(s["sender_email"], "")
        self.assertEqual(s["merchant_notify_email"], "owner@test.es")
        self.assertTrue(s["notify_merchant_on_cart"])

    def test_discord_payload_has_no_parse_mode(self):
        resp = MagicMock(status_code=204)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp) as mock_post:
            res = run(MobileNotifier().send_discord_notification("https://discord.com/api/webhooks/1/x", {"title": "t"}))
        self.assertTrue(res["ok"])
        self.assertNotIn("parse_mode", mock_post.call_args[1]["json"])


if __name__ == "__main__":
    unittest.main()

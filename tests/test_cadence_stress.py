"""
Empirical Stress Test Harness & Adversarial Validation for DripCadenceManager & Cadence State Machine.
Challenger M1-2: Cadence State Machine Challenger.

Stress test suites:
1. Microsecond & sub-second boundary transitions (1799s vs 1800s, 14399s vs 14400s, 86399s vs 86400s, 259200s vs 259201s).
2. Leap days, leap years, and calendar boundary transitions (Feb 28-29, Feb 29-Mar 1, centurial years, year rollover).
3. Out-of-order stage updates, monotonicity, and state transition invariance.
4. Order conversion matching resolution (checkout_id, checkout_token, case-insensitive email, whitespace, nested customer).
5. Idempotency of conversion reconciliation and terminal state immutability.
6. URL discount injection / stripping stress and stage metadata invariants.
7. Database level adversarial checks: column safety and terminal state protection.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import sqlite3
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from cadence_manager import DripCadenceManager
import database as db


class TestMicrosecondBoundaries(unittest.TestCase):
    """
    Sub-second & microsecond boundary stress tests for DripCadenceManager.
    Evaluates exact floating-point second thresholds and epsilon perturbations.
    """

    def setUp(self):
        self.cadence = DripCadenceManager()
        self.base_now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)

    # ── Stage 1: 30 minutes (1,800 seconds) ───────────────────────────────────

    def test_stage_1_exact_1799s_returns_none(self):
        """At 1799.0s post-abandonment, Stage 1 must NOT trigger."""
        cart_dt = self.base_now - timedelta(seconds=1799)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_stage_1_subsecond_1799_999999s_returns_none(self):
        """At 1799.999999s (1 microsecond before 30m), Stage 1 must NOT trigger."""
        cart_dt = self.base_now - timedelta(seconds=1799, microseconds=999999)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_stage_1_exact_1800s_returns_1(self):
        """At exactly 1800.0s (30m), Stage 1 MUST trigger."""
        cart_dt = self.base_now - timedelta(seconds=1800)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 1)

    def test_stage_1_subsecond_1800_000001s_returns_1(self):
        """At 1800.000001s (1 microsecond past 30m), Stage 1 MUST trigger."""
        cart_dt = self.base_now - timedelta(seconds=1800, microseconds=1)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 1)

    # ── Stage 2: 4 hours (14,400 seconds) ─────────────────────────────────────

    def test_stage_2_exact_14399s_returns_none(self):
        """At 14399.0s post-abandonment, Stage 2 must NOT trigger."""
        cart_dt = self.base_now - timedelta(seconds=14399)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 1, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_stage_2_subsecond_14399_999999s_returns_none(self):
        """At 14399.999999s (1 microsecond before 4h), Stage 2 must NOT trigger."""
        cart_dt = self.base_now - timedelta(seconds=14399, microseconds=999999)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 1, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_stage_2_exact_14400s_returns_2(self):
        """At exactly 14400.0s (4h), Stage 2 MUST trigger."""
        cart_dt = self.base_now - timedelta(seconds=14400)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 1, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 2)

    def test_stage_2_subsecond_14400_000001s_returns_2(self):
        """At 14400.000001s (1 microsecond past 4h), Stage 2 MUST trigger."""
        cart_dt = self.base_now - timedelta(seconds=14400, microseconds=1)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 1, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 2)

    # ── Stage 3: 24 hours (86,400 seconds) ────────────────────────────────────

    def test_stage_3_exact_86399s_returns_none(self):
        """At 86399.0s post-abandonment, Stage 3 must NOT trigger."""
        cart_dt = self.base_now - timedelta(seconds=86399)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_stage_3_subsecond_86399_999999s_returns_none(self):
        """At 86399.999999s (1 microsecond before 24h), Stage 3 must NOT trigger."""
        cart_dt = self.base_now - timedelta(seconds=86399, microseconds=999999)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_stage_3_exact_86400s_returns_3(self):
        """At exactly 86400.0s (24h), Stage 3 MUST trigger."""
        cart_dt = self.base_now - timedelta(seconds=86400)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 3)

    def test_stage_3_subsecond_86400_000001s_returns_3(self):
        """At 86400.000001s (1 microsecond past 24h), Stage 3 MUST trigger."""
        cart_dt = self.base_now - timedelta(seconds=86400, microseconds=1)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 3)

    # ── Cutoff: 72 hours (259,200 seconds) ────────────────────────────────────

    def test_cutoff_exact_259199s_eligible_for_stage_3(self):
        """At 259199s (71h 59m 59s), still within 72h window, triggers Stage 3."""
        cart_dt = self.base_now - timedelta(seconds=259199)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 3)

    def test_cutoff_exact_259200s_boundary(self):
        """At exactly 259200.0s (72h 00m 00s), age <= CADENCE_CUTOFF_SECONDS, triggers Stage 3."""
        cart_dt = self.base_now - timedelta(seconds=259200)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.base_now), 3)

    def test_cutoff_subsecond_259200_000001s_exhausted(self):
        """At 259200.000001s (1 microsecond past 72h), cutoff exceeded, returns None."""
        cart_dt = self.base_now - timedelta(seconds=259200, microseconds=1)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_cutoff_exact_259201s_exhausted(self):
        """At 259201s (72h 00m 01s), cutoff exceeded, returns None."""
        cart_dt = self.base_now - timedelta(seconds=259201)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    # ── Negative Age / Future Clock Skew ──────────────────────────────────────

    def test_future_clock_skew_subsecond_returns_none(self):
        """Cart created 1 microsecond in the future (clock skew) must return None."""
        cart_dt = self.base_now + timedelta(microseconds=1)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))

    def test_future_clock_skew_large_returns_none(self):
        """Cart created 1 hour in the future must return None."""
        cart_dt = self.base_now + timedelta(hours=1)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.base_now))


class TestLeapDayBoundaries(unittest.TestCase):
    """
    Empirical calendar tests across leap days (Feb 29), leap years, and calendar boundaries.
    """

    def setUp(self):
        self.cadence = DripCadenceManager()

    def test_leap_day_2024_02_28_crosses_into_leap_day(self):
        """Cart created 2024-02-28 23:45:00 UTC crosses into 2024-02-29 00:15:00 UTC (30m)."""
        cart_dt = datetime(2024, 2, 28, 23, 45, 0, tzinfo=timezone.utc)
        now_dt = datetime(2024, 2, 29, 0, 15, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_leap1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        # At 29m (2024-02-29 00:14:00 UTC) -> None
        early = datetime(2024, 2, 29, 0, 14, 0, tzinfo=timezone.utc)
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, early))

        # At 30m (2024-02-29 00:15:00 UTC) -> Stage 1
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 1)

    def test_leap_day_2024_02_29_crosses_into_march_1(self):
        """Cart created 2024-02-29 23:45:00 UTC crosses into 2024-03-01 00:15:00 UTC (30m)."""
        cart_dt = datetime(2024, 2, 29, 23, 45, 0, tzinfo=timezone.utc)
        now_dt = datetime(2024, 3, 1, 0, 15, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_leap2", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 1)

    def test_leap_day_stage_2_4h_transition(self):
        """Cart created 2024-02-28 22:00:00 UTC reaches 4h at 2024-02-29 02:00:00 UTC."""
        cart_dt = datetime(2024, 2, 28, 22, 0, 0, tzinfo=timezone.utc)
        now_dt = datetime(2024, 2, 29, 2, 0, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_leap3", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 1, "status": "active"}

        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 2)

    def test_leap_day_stage_3_24h_transition(self):
        """Cart created 2024-02-28 12:00:00 UTC reaches 24h at 2024-02-29 12:00:00 UTC."""
        cart_dt = datetime(2024, 2, 28, 12, 0, 0, tzinfo=timezone.utc)
        now_dt = datetime(2024, 2, 29, 12, 0, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_leap4", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}

        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 3)

    def test_leap_day_cutoff_72h_transition(self):
        """Cart created 2024-02-27 12:00:00 UTC across leap day: 72h arrives on 2024-03-01 12:00:00 UTC."""
        cart_dt = datetime(2024, 2, 27, 12, 0, 0, tzinfo=timezone.utc)
        now_dt = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_leap5", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}

        # At exactly 72h: still eligible
        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 3)

        # At 72h + 1s: cutoff triggered
        cutoff_dt = now_dt + timedelta(seconds=1)
        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, cutoff_dt))

    def test_non_leap_year_2025_crosses_march_1(self):
        """Non-leap year 2025: Feb 28 23:45 UTC -> Mar 01 00:15 UTC (30m)."""
        cart_dt = datetime(2025, 2, 28, 23, 45, 0, tzinfo=timezone.utc)
        now_dt = datetime(2025, 3, 1, 0, 15, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_nonleap", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 1)

    def test_future_leap_year_2028(self):
        """Future leap year 2028: Feb 29 exists and operates with exact second precision."""
        cart_dt = datetime(2028, 2, 29, 10, 0, 0, tzinfo=timezone.utc)
        now_dt = datetime(2028, 2, 29, 10, 30, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_2028", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 1)

    def test_year_rollover_dec_31_to_jan_1(self):
        """Year rollover from 2026-12-31 23:45 UTC to 2027-01-01 00:15 UTC (30m)."""
        cart_dt = datetime(2026, 12, 31, 23, 45, 0, tzinfo=timezone.utc)
        now_dt = datetime(2027, 1, 1, 0, 15, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_nye", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, now_dt), 1)


class TestStateTransitionInvariants(unittest.TestCase):
    """
    Adversarial challenge on state machine invariants:
    - Zero skipping of stages (0 -> 1 -> 2 -> 3 strictly monotonic).
    - Zero re-triggering of stages already processed.
    - Zero regressions (e.g. stage 2 evaluated to 1).
    - Out-of-bounds stage numbers handling.
    - Terminal state immutability (converted, exhausted, canceled).
    """

    def setUp(self):
        self.cadence = DripCadenceManager()
        self.now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)

    def test_stage_0_at_5_hours_returns_stage_1_not_stage_2(self):
        """Even if cart is 5h old, an uncontacted cart (stage 0) must trigger Stage 1 first."""
        cart_dt = self.now - timedelta(hours=5)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        res = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertEqual(res, 1, "Must trigger Stage 1 first, cannot skip to Stage 2")

    def test_stage_0_at_30_hours_returns_stage_1_not_stage_3(self):
        """Even if cart is 30h old, an uncontacted cart (stage 0) must trigger Stage 1 first."""
        cart_dt = self.now - timedelta(hours=30)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        res = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertEqual(res, 1, "Must trigger Stage 1 first, cannot skip directly to Stage 3")

    def test_stage_1_at_30_hours_returns_stage_2_not_stage_3(self):
        """If checkout is at Stage 1 and cart is 30h old, must trigger Stage 2 next."""
        cart_dt = self.now - timedelta(hours=30)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 1, "status": "active"}

        res = self.cadence.evaluate_drip_stage(checkout, state, self.now)
        self.assertEqual(res, 2, "Must trigger Stage 2, cannot skip directly from 1 to 3")

    def test_stage_1_evaluated_too_early_returns_none(self):
        """Checkout at Stage 1, age is 45m (not 4h yet): must return None."""
        cart_dt = self.now - timedelta(minutes=45)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 1, "status": "active"}

        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.now))

    def test_stage_2_evaluated_too_early_returns_none(self):
        """Checkout at Stage 2, age is 6h (not 24h yet): must return None."""
        cart_dt = self.now - timedelta(hours=6)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": 2, "status": "active"}

        self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.now))

    def test_stage_3_already_completed_returns_none(self):
        """Checkout at Stage 3: terminal stage, must always return None."""
        for hours in [25, 30, 48, 70, 75]:
            cart_dt = self.now - timedelta(hours=hours)
            checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
            state = {"current_stage": 3, "status": "active"}
            self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.now))

    def test_stage_out_of_bounds_returns_none(self):
        """Anomalous stages (-1, 4, 99) must return None without crashing."""
        cart_dt = self.now - timedelta(hours=5)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}

        for invalid_stage in [-1, -99, 4, 5, 99]:
            state = {"current_stage": invalid_stage, "status": "active"}
            self.assertIsNone(self.cadence.evaluate_drip_stage(checkout, state, self.now))

    def test_string_encoded_stage_parsed(self):
        """Stage passed as string '0', '1', '2' must be safely parsed as int."""
        cart_dt = self.now - timedelta(hours=5)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}
        state = {"current_stage": "1", "status": "active"}

        self.assertEqual(self.cadence.evaluate_drip_stage(checkout, state, self.now), 2)

    def test_terminal_statuses_halt_all_evaluations(self):
        """Non-active statuses ('converted', 'exhausted', 'canceled', 'opted_out') return None."""
        cart_dt = self.now - timedelta(hours=10)
        checkout = {"id": "c1", "created_at": cart_dt.isoformat()}

        for term_status in ["converted", "exhausted", "canceled", "opted_out", "archived", "unknown"]:
            state = {"current_stage": 1, "status": term_status}
            self.assertIsNone(
                self.cadence.evaluate_drip_stage(checkout, state, self.now),
                f"Status '{term_status}' must permanently halt transitions"
            )

    def test_monotonic_full_lifecycle_simulation(self):
        """
        Oracular test: Simulates a checkout from abandonment (t=0) through t=75h.
        Asserts exact monotonic transitions:
        0 -> 1 (at 30m) -> 2 (at 4h) -> 3 (at 24h) -> Stop (at 72h).
        Zero regressions or unexpected transitions.
        """
        start = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        checkout = {"id": "c_oracle", "created_at": start.isoformat()}
        state = {"current_stage": 0, "status": "active"}

        transitions = []
        # Sample every 10 minutes for 75 hours
        for mins in range(0, 75 * 60 + 1, 10):
            sim_now = start + timedelta(minutes=mins)
            stage_trigger = self.cadence.evaluate_drip_stage(checkout, state, sim_now)
            if stage_trigger is not None:
                transitions.append((mins, state["current_stage"], stage_trigger))
                state["current_stage"] = stage_trigger

        expected = [
            (30, 0, 1),    # At 30m: advances 0 -> 1
            (240, 1, 2),   # At 240m (4h): advances 1 -> 2
            (1440, 2, 3),  # At 1440m (24h): advances 2 -> 3
        ]
        self.assertEqual(transitions, expected, "Cadence must follow strict 0->1, 1->2, 2->3 sequence")


class TestConversionMatchingResolution(unittest.TestCase):
    """
    Empirical tests for order conversion reconciliation matching logic:
    - Matching by checkout_id (string vs int).
    - Matching by checkout_token.
    - Matching by email (case insensitivity, whitespace trimming).
    - Matching top-level email vs nested customer dict.
    - Protection against empty/None identifiers.
    - Shop domain isolation.
    """

    def setUp(self):
        self.cadence = DripCadenceManager()
        # Set up in-memory SQLite database simulating checkout_drip_states table
        self.sqlite_conn = sqlite3.connect(":memory:")
        self.sqlite_conn.execute("""
            CREATE TABLE checkout_drip_states (
                id INTEGER PRIMARY KEY,
                shop_domain TEXT NOT NULL,
                checkout_id TEXT UNIQUE NOT NULL,
                checkout_token TEXT,
                email TEXT,
                phone TEXT,
                customer_name TEXT,
                checkout_url TEXT NOT NULL,
                total_price REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'EUR',
                items TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                current_stage INTEGER DEFAULT 0,
                stage_1_sent_at TEXT,
                stage_2_sent_at TEXT,
                stage_3_sent_at TEXT,
                status TEXT DEFAULT 'active',
                converted_at TEXT,
                converted_order_id TEXT,
                revenue_recovered REAL DEFAULT 0.0,
                updated_at TEXT
            )
        """)
        self.sqlite_conn.commit()

    def _seed_checkout(self, shop="test.myshopify.com", cid="1001", token="tok_abc", email="elena@example.com", status="active", stage=1):
        self.sqlite_conn.execute("""
            INSERT INTO checkout_drip_states (shop_domain, checkout_id, checkout_token, email, status, current_stage, checkout_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'https://checkout.url', '2026-10-26 10:00:00')
        """, (shop, str(cid), token, email, status, stage))
        self.sqlite_conn.commit()

    def _execute_mark_converted(self, shop, checkout_id=None, email=None, checkout_token=None, order_id="ord_99", revenue=145.0):
        """Simulates db.mark_drip_converted query directly against SQLite."""
        cid_str = str(checkout_id) if checkout_id else None
        token_str = str(checkout_token) if checkout_token else None
        email_clean = email.strip().lower() if email else None

        sql = """
            UPDATE checkout_drip_states
            SET status = 'converted',
                converted_at = CURRENT_TIMESTAMP,
                converted_order_id = ?,
                revenue_recovered = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE shop_domain = ?
              AND status = 'active'
              AND (
                  (? IS NOT NULL AND checkout_id = ?)
                  OR (? IS NOT NULL AND checkout_token = ?)
                  OR (? IS NOT NULL AND LOWER(email) = ? AND email != '')
              )
        """
        cur = self.sqlite_conn.cursor()
        cur.execute(sql, (str(order_id or ""), revenue, shop, cid_str, cid_str, token_str, token_str, email_clean, email_clean))
        self.sqlite_conn.commit()
        return cur.rowcount

    def test_match_by_checkout_id_exact(self):
        """Order with checkout_id matching active cart converts it."""
        self._seed_checkout(cid="c_555", token="tok_xyz", email="buyer@test.com")
        rows = self._execute_mark_converted(shop="test.myshopify.com", checkout_id="c_555")
        self.assertEqual(rows, 1)

        cur = self.sqlite_conn.cursor()
        cur.execute("SELECT status, converted_order_id FROM checkout_drip_states WHERE checkout_id = 'c_555'")
        row = cur.fetchone()
        self.assertEqual(row[0], "converted")
        self.assertEqual(row[1], "ord_99")

    def test_match_by_checkout_id_integer(self):
        """Order with integer checkout_id matches string checkout_id in database."""
        self._seed_checkout(cid="9999", token="tok_num", email="num@test.com")
        rows = self._execute_mark_converted(shop="test.myshopify.com", checkout_id=9999)
        self.assertEqual(rows, 1)

    def test_match_by_checkout_token(self):
        """Order with checkout_token (and no checkout_id) matches active cart."""
        self._seed_checkout(cid="c_token_test", token="tok_secret_123", email="user@test.com")
        rows = self._execute_mark_converted(shop="test.myshopify.com", checkout_token="tok_secret_123")
        self.assertEqual(rows, 1)

    def test_match_by_email_case_insensitive(self):
        """Order with uppercase email matches lowercase email in database."""
        self._seed_checkout(cid="c_email_case", email="elena.popescu@example.com")
        rows = self._execute_mark_converted(shop="test.myshopify.com", email="ELENA.POPESCU@EXAMPLE.COM")
        self.assertEqual(rows, 1)

    def test_match_by_email_with_surrounding_whitespace(self):
        """Order with whitespace around email matches trimmed email."""
        self._seed_checkout(cid="c_email_space", email="elena@example.com")
        rows = self._execute_mark_converted(shop="test.myshopify.com", email="   elena@example.com   ")
        self.assertEqual(rows, 1)

    def test_mark_order_converted_extracts_nested_customer_email(self):
        """DripCadenceManager.mark_order_converted extracts email from customer dict."""
        order = {
            "id": 1234,
            "total_price": "200.00",
            "customer": {"email": "nested@example.com"}
        }
        with patch("cadence_manager.db.mark_drip_converted") as mock_db:
            mock_db.return_value = 1
            res = self.cadence.mark_order_converted("test.myshopify.com", order)
            self.assertTrue(res)
            mock_db.assert_called_once_with(
                shop="test.myshopify.com",
                checkout_id=None,
                email="nested@example.com",
                checkout_token=None,
                order_id="1234",
                revenue=200.0
            )

    def test_mark_order_converted_extracts_toplevel_email(self):
        """DripCadenceManager.mark_order_converted extracts email from top-level order."""
        order = {
            "id": 5678,
            "email": "top@example.com",
            "total_price": "50.00"
        }
        with patch("cadence_manager.db.mark_drip_converted") as mock_db:
            mock_db.return_value = 1
            res = self.cadence.mark_order_converted("test.myshopify.com", order)
            self.assertTrue(res)
            mock_db.assert_called_once_with(
                shop="test.myshopify.com",
                checkout_id=None,
                email="top@example.com",
                checkout_token=None,
                order_id="5678",
                revenue=50.0
            )

    def test_empty_identifiers_do_not_convert_any_checkouts(self):
        """Order with None or empty checkout_id, token, and email must convert 0 rows."""
        self._seed_checkout(cid="c_safe", token="tok_safe", email="safe@example.com")
        rows = self._execute_mark_converted(shop="test.myshopify.com", checkout_id=None, email=None, checkout_token=None)
        self.assertEqual(rows, 0)

        # Check cart remains active
        cur = self.sqlite_conn.cursor()
        cur.execute("SELECT status FROM checkout_drip_states WHERE checkout_id = 'c_safe'")
        self.assertEqual(cur.fetchone()[0], "active")

    def test_cross_shop_domain_isolation(self):
        """Order for shop B must NOT convert matching checkout in shop A."""
        self._seed_checkout(shop="shop-a.myshopify.com", cid="c_iso", email="common@example.com")
        rows = self._execute_mark_converted(shop="shop-b.myshopify.com", email="common@example.com")
        self.assertEqual(rows, 0, "Cross-shop reconciliation must never affect other stores")

        cur = self.sqlite_conn.cursor()
        cur.execute("SELECT status FROM checkout_drip_states WHERE checkout_id = 'c_iso'")
        self.assertEqual(cur.fetchone()[0], "active")


    def tearDown(self):
        if hasattr(self, "sqlite_conn"):
            self.sqlite_conn.close()


class TestConversionIdempotency(unittest.TestCase):
    """
    Empirical tests for idempotency of conversion reconciliation:
    - Multiple reconciliation passes with the same order must be safe no-ops.
    - Converted state is terminal and immutable.
    """

    def setUp(self):
        self.sqlite_conn = sqlite3.connect(":memory:")
        self.sqlite_conn.execute("""
            CREATE TABLE checkout_drip_states (
                id INTEGER PRIMARY KEY,
                shop_domain TEXT NOT NULL,
                checkout_id TEXT UNIQUE NOT NULL,
                checkout_token TEXT,
                email TEXT,
                status TEXT DEFAULT 'active',
                current_stage INTEGER DEFAULT 0,
                checkout_url TEXT NOT NULL,
                converted_at TEXT,
                converted_order_id TEXT,
                revenue_recovered REAL DEFAULT 0.0,
                updated_at TEXT
            )
        """)
        self.sqlite_conn.execute("""
            INSERT INTO checkout_drip_states (shop_domain, checkout_id, checkout_token, email, status, current_stage, checkout_url)
            VALUES ('store.myshopify.com', 'c_idem', 'tok_idem', 'buyer@store.com', 'active', 1, 'https://url')
        """)
        self.sqlite_conn.commit()

    def tearDown(self):
        if hasattr(self, "sqlite_conn"):
            self.sqlite_conn.close()

    def _mark_converted(self, shop="store.myshopify.com", cid="c_idem", email="buyer@store.com", order_id="ord_100", revenue=180.0):
        sql = """
            UPDATE checkout_drip_states
            SET status = 'converted',
                converted_at = CURRENT_TIMESTAMP,
                converted_order_id = ?,
                revenue_recovered = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE shop_domain = ?
              AND status = 'active'
              AND (
                  (? IS NOT NULL AND checkout_id = ?)
                  OR (? IS NOT NULL AND LOWER(email) = ? AND email != '')
              )
        """
        cur = self.sqlite_conn.cursor()
        cur.execute(sql, (order_id, revenue, shop, cid, cid, email, email))
        self.sqlite_conn.commit()
        return cur.rowcount

    def test_conversion_reconciliation_is_strictly_idempotent(self):
        """
        Calling conversion reconciliation 3 times with the exact same order:
        - Call 1: Updates 1 row (status -> converted)
        - Call 2: Updates 0 rows (no-op, already converted)
        - Call 3: Updates 0 rows (no-op, already converted)
        """
        r1 = self._mark_converted()
        self.assertEqual(r1, 1, "First reconciliation must update the active row")

        r2 = self._mark_converted()
        self.assertEqual(r2, 0, "Duplicate reconciliation must be a no-op")

        r3 = self._mark_converted()
        self.assertEqual(r3, 0, "Triplicate reconciliation must be a no-op")

        cur = self.sqlite_conn.cursor()
        cur.execute("SELECT status, converted_order_id, revenue_recovered FROM checkout_drip_states WHERE checkout_id = 'c_idem'")
        row = cur.fetchone()
        self.assertEqual(row[0], "converted")
        self.assertEqual(row[1], "ord_100")
        self.assertEqual(row[2], 180.0)


class TestURLAndMetadataStress(unittest.TestCase):
    """
    Stress-testing URL generation, discount stripping / injection, and metadata structure.
    """

    def setUp(self):
        self.cadence = DripCadenceManager()

    def test_stage_1_strips_case_insensitive_discounts(self):
        """Stage 1 strips discount parameter regardless of casing (DISCOUNT, Discount, discount)."""
        variations = [
            ("https://shop.com/c/1?discount=MG10", "https://shop.com/c/1"),
            ("https://shop.com/c/1?DISCOUNT=MG10", "https://shop.com/c/1"),
            ("https://shop.com/c/1?DiScOuNt=VIP", "https://shop.com/c/1"),
            ("https://shop.com/c/1?discount=A&discount=B", "https://shop.com/c/1"),
            ("https://shop.com/c/1?locale=ro&discount=MG10&step=payment", "https://shop.com/c/1?locale=ro&step=payment"),
        ]
        for raw, expected in variations:
            clean = self.cadence.build_stage_checkout_url(raw, stage=1)
            self.assertEqual(clean, expected)

    def test_stage_2_and_3_injects_and_replaces_discount(self):
        """Stages 2 and 3 inject MG10, replacing any existing discount."""
        variations = [
            ("https://shop.com/c/1", 2, "https://shop.com/c/1?discount=MG10"),
            ("https://shop.com/c/1?discount=OLD50", 2, "https://shop.com/c/1?discount=MG10"),
            ("https://shop.com/c/1?utm=ad&discount=OLD", 3, "https://shop.com/c/1?utm=ad&discount=MG10"),
        ]
        for raw, stage, expected in variations:
            url = self.cadence.build_stage_checkout_url(raw, stage=stage)
            self.assertEqual(url, expected)

    def test_stage_url_preserves_url_fragment(self):
        """URL fragments (#summary) are preserved after query param injection."""
        url = self.cadence.build_stage_checkout_url("https://shop.com/c/1#summary", stage=2)
        self.assertEqual(url, "https://shop.com/c/1?discount=MG10#summary")

    def test_stage_metadata_structure_and_invariants(self):
        """Validates contract of stage metadata for all stages."""
        m1 = self.cadence.get_stage_metadata(1)
        self.assertEqual(m1["stage"], 1)
        self.assertIsNone(m1["discount_code"])
        self.assertFalse(m1["has_discount"])
        self.assertFalse(m1["urgency"])

        m2 = self.cadence.get_stage_metadata(2)
        self.assertEqual(m2["stage"], 2)
        self.assertEqual(m2["discount_code"], "MG10")
        self.assertTrue(m2["has_discount"])
        self.assertEqual(m2["discount_percent"], 10)
        self.assertFalse(m2["urgency"])

        m3 = self.cadence.get_stage_metadata(3)
        self.assertEqual(m3["stage"], 3)
        self.assertEqual(m3["discount_code"], "MG10")
        self.assertTrue(m3["has_discount"])
        self.assertEqual(m3["discount_percent"], 10)
        self.assertTrue(m3["urgency"])

        for invalid in [0, 4, -1, 99]:
            with self.assertRaises(ValueError):
                self.cadence.get_stage_metadata(invalid)


class TestAdversarialDatabaseInvariants(unittest.TestCase):
    """
    Adversarial analysis of backend/database.py methods for cadence states.
    Tests SQL construction, column boundaries, and terminal state immutability.
    """

    def test_database_update_drip_stage_sql_and_column_boundary(self):
        """
        Adversarial inspection of db.update_drip_stage:
        Validates the generated SQL for valid stages (1, 2, 3) and detects vulnerability if stage >= 4.
        """
        with patch("database.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur

            # Call for valid stage 1
            now_dt = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
            db.update_drip_stage("c_test", 1, now_dt)
            executed_sql = mock_cur.execute.call_args[0][0]
            self.assertIn("stage_1_sent_at", executed_sql)
            self.assertNotIn("status = 'exhausted'", executed_sql)

            # Call for stage 3: sets status = 'exhausted'
            db.update_drip_stage("c_test", 3, now_dt)
            executed_sql_3 = mock_cur.execute.call_args[0][0]
            self.assertIn("stage_3_sent_at", executed_sql_3)
            self.assertIn("status = 'exhausted'", executed_sql_3)

            # [EMPIRICAL ADVERSARIAL CHECK] Invalid stage 4 produces non-existent column
            db.update_drip_stage("c_test", 4, now_dt)
            executed_sql_4 = mock_cur.execute.call_args[0][0]
            self.assertIn("stage_4_sent_at", executed_sql_4)
            # In PostgreSQL schema, column stage_4_sent_at does NOT exist!

    def test_update_drip_stage_lacks_active_status_guard_adversarial(self):
        """
        [EMPIRICAL ADVERSARIAL FINDING]
        db.update_drip_stage has no 'AND status = active' filter in its WHERE clause.
        If called with stage=3 on a checkout that was already converted,
        it will overwrite status = 'exhausted', clobbering the 'converted' state.
        """
        with patch("database.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur

            now_dt = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
            db.update_drip_stage("c_converted_1", 3, now_dt)
            executed_sql = mock_cur.execute.call_args[0][0]

            # Observe: SQL does NOT protect converted states
            self.assertNotIn("status = 'active'", executed_sql)
            self.assertNotIn("status NOT IN", executed_sql)

    def test_upsert_preserves_converted_and_canceled_states(self):
        """
        Verifies that upsert_checkout_drip_state preserves 'converted' status
        via its WHERE status NOT IN ('converted', 'canceled') clause.
        """
        with patch("database.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_get_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_cur.fetchone.return_value = None  # Simulates UPDATE filtered out by WHERE
            mock_cur.fetchall.return_value = []

            checkout_sample = {
                "id": "c_converted_123",
                "checkout_url": "https://url",
                "email": "test@test.com"
            }
            db.upsert_checkout_drip_state("shop.myshopify.com", checkout_sample)

            # Verify the INSERT ... ON CONFLICT query includes the protection clause
            upsert_sql = mock_cur.execute.call_args_list[0][0][0]
            self.assertIn("WHERE checkout_drip_states.status NOT IN ('converted', 'canceled')", upsert_sql)

    def test_mark_order_converted_robustness_on_non_numeric_price(self):
        """
        [EMPIRICAL ADVERSARIAL FINDING]
        If Shopify order contains total_price with non-numeric value ('free' or '145,00'),
        float(order_dict.get('total_price') or 0.0) raises ValueError without exception handling.
        """
        cadence = DripCadenceManager()
        order_invalid = {"id": 100, "checkout_id": "c1", "total_price": "free"}
        with self.assertRaises(ValueError):
            cadence.mark_order_converted("shop.myshopify.com", order_invalid)


class TestTimezoneExtremesAndDatetimes(unittest.TestCase):
    """
    Stress-testing timezone offsets:
    - UTC+14 (Line Islands, Kiribati)
    - UTC-12 (Baker Island)
    - Naive datetimes vs aware datetimes
    """

    def setUp(self):
        self.cadence = DripCadenceManager()

    def test_timezone_extremes_utc_plus_14_vs_utc_minus_12(self):
        """
        Checkout created in UTC+14 vs evaluated in UTC-12:
        Normalized UTC time delta must be strictly identical regardless of store local timezone.
        """
        # 2026-10-26 14:00:00+14:00 is 2026-10-26 00:00:00 UTC
        created_str = "2026-10-26T14:00:00+14:00"
        # 35 minutes later in UTC-12: 2026-10-25 12:35:00-12:00 is 2026-10-26 00:35:00 UTC
        now_dt = datetime.fromisoformat("2026-10-25T12:35:00-12:00")

        checkout = {"id": "c_tz", "created_at": created_str}
        state = {"current_stage": 0, "status": "active"}

        stage = self.cadence.evaluate_drip_stage(checkout, state, now_dt)
        self.assertEqual(stage, 1, "Must correctly compute 35m across extreme timezone offsets (+14 vs -12)")

    def test_naive_datetime_normalized_to_utc(self):
        """Naive datetime is treated as UTC without crashing."""
        naive_dt = datetime(2026, 10, 26, 12, 0, 0)
        parsed = self.cadence.parse_datetime(naive_dt)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.tzinfo, timezone.utc)




if __name__ == "__main__":
    unittest.main()

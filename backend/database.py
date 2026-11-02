"""
Persistence layer for Jarvis (PostgreSQL in production, SQLite for local/tests).

Design rules (see CONTRACT.md):
- If DATABASE_URL is configured, PostgreSQL is mandatory: when it is unreachable we
  raise instead of silently writing into an ephemeral SQLite file.
- DB errors on commit are never swallowed (callers must not report success).
- SQLite file path comes from env JARVIS_SQLITE_PATH (default backend/jarvis.db).
- Marketing consent is tri-state: True / False / None (unknown == NO consent).
  Email consent is keyed by normalized email, WhatsApp/SMS consent by normalized
  phone, and email consent never authorizes WhatsApp. Opt-out always wins and
  survives GDPR redaction through a hashed suppression entry.
"""

import os
import re
import json
import hashlib
import logging
import sqlite3
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Optional, Any, Union, Iterable, Tuple

import psycopg2
import psycopg2.extras

logger = logging.getLogger("jarvis.database")

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("DATABASE_PUBLIC_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("POSTGRESQL_URL")
    or ""
)

_DEFAULT_SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis.db")
SQLITE_PATH = os.getenv("JARVIS_SQLITE_PATH") or _DEFAULT_SQLITE_PATH
USING_SQLITE = not bool(DATABASE_URL)


class DatabaseUnavailableError(RuntimeError):
    """Raised when DATABASE_URL is configured but PostgreSQL cannot be reached."""


def _sqlite_path() -> str:
    return os.getenv("JARVIS_SQLITE_PATH") or SQLITE_PATH


# ── Normalization helpers ─────────────────────────────────────────────────────

def normalize_email(value: Any) -> Optional[str]:
    """Canonical email key: stripped + lower-cased. None when empty."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    clean = value.strip().lower()
    return clean or None


def normalize_phone(value: Any) -> Optional[str]:
    """
    Canonical phone key = the exact digits WhatsApp is sent to.
    Digits only, leading international '00' removed, country code kept
    ("+34 699 333 444" == "0034699333444" == "34699333444").
    National formats get the same country heuristics as the WhatsApp dispatcher
    (IT 3xxxxxxxxx, ES 6/7xxxxxxxx, RO 07xxxxxxxx, DE 01xxxxxxxxx), so that the
    consent / opt-out key always equals the number a message would go to.
    Returns None when no digits are present.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    digits = "".join(str(int(ch)) for ch in value if ch.isdecimal())
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return None
    # Romanian typo "+40 0722..." -> drop the national trunk 0
    if len(digits) == 12 and digits.startswith("400") and digits[3] == "7":
        return "40" + digits[3:]
    if len(digits) == 10 and digits.startswith("3"):
        return "39" + digits
    if len(digits) == 9 and digits[0] in ("6", "7"):
        return "34" + digits
    if len(digits) == 10 and digits.startswith("07"):
        return "40" + digits[1:]
    if digits.startswith("01") and len(digits) in (11, 12):
        return "49" + digits[1:]
    return digits


def identity_hash(normalized_identifier: str) -> str:
    """sha256 hex digest of an already-normalized email / phone (suppression key)."""
    return hashlib.sha256((normalized_identifier or "").encode("utf-8")).hexdigest()


def _utc_naive(dt: Optional[datetime] = None) -> datetime:
    """UTC timestamp without tzinfo (portable across TIMESTAMP columns on PG and SQLite)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_tristate(value: Any) -> Optional[bool]:
    """True / False / None from bools, ints and common Shopify strings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y", "subscribed", "opted_in", "granted"):
            return True
        if v in ("false", "0", "no", "n", "unsubscribed", "not_subscribed", "denied", "redacted", "invalid"):
            return False
        return None
    return None


# ── Connection wrappers ───────────────────────────────────────────────────────

def _sqlite_param(p: Any) -> Any:
    if isinstance(p, bool):
        return 1 if p else 0
    if isinstance(p, (dict, list)):
        return json.dumps(p)
    if isinstance(p, datetime):
        if p.tzinfo is not None:
            p = p.astimezone(timezone.utc)
        return p.isoformat(sep=" ")
    if isinstance(p, date):
        return p.isoformat()
    if isinstance(p, Decimal):
        return float(p)
    return p


class SQLiteCursor:
    def __init__(self, cursor):
        self.cur = cursor

    def execute(self, sql, params=None):
        clean_sql = sql
        clean_sql = re.sub(r'::[a-zA-Z0-9_]+', '', clean_sql)
        clean_sql = re.sub(r'\bSERIAL\s+PRIMARY\s+KEY\b', 'INTEGER PRIMARY KEY AUTOINCREMENT', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bNOW\(\)', 'CURRENT_TIMESTAMP', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bJSONB\b', 'TEXT', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bTIMESTAMP\s+WITH\s+TIME\s+ZONE\b', 'TIMESTAMP', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bBOOLEAN\s+DEFAULT\s+TRUE\b', 'INTEGER DEFAULT 1', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bBOOLEAN\s+DEFAULT\s+FALSE\b', 'INTEGER DEFAULT 0', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bNUMERIC\b', 'REAL', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bVARCHAR\(\d+\)', 'TEXT', clean_sql, flags=re.I)
        clean_sql = re.sub(r'\bADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b', 'ADD COLUMN', clean_sql, flags=re.I)
        clean_sql = clean_sql.replace('%s', '?').replace('%%', '%')

        statements = [s.strip() for s in clean_sql.split(';') if s.strip()]
        for stmt in statements:
            if params is not None and len(statements) == 1:
                clean_params = [_sqlite_param(p) for p in params]
                return self.cur.execute(stmt, clean_params)
            else:
                try:
                    self.cur.execute(stmt)
                except sqlite3.OperationalError as e:
                    err_msg = str(e).lower()
                    if "duplicate column" in err_msg or "already exists" in err_msg:
                        pass
                    else:
                        raise e
        return self

    def fetchone(self):
        row = self.cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        rows = self.cur.fetchall()
        return [dict(r) for r in rows]

    def __getattr__(self, name):
        return getattr(self.cur, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.cur.close()
        except Exception:
            pass


class SQLiteConnection:
    def __init__(self, db_path: Optional[str] = None):
        path = db_path or _sqlite_path()
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        self.db_path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row

    def cursor(self):
        return SQLiteCursor(self.conn.cursor())

    def commit(self):
        """Commit; errors are logged and re-raised (never silently swallowed)."""
        try:
            self.conn.commit()
        except Exception as e:
            logger.error("[DB] SQLite commit failed (%s): %s", self.db_path, e)
            raise

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception as e:
            logger.error("[DB] SQLite rollback failed: %s", e)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


class PGConnection:
    """Thin wrapper so `with get_conn() as conn` commits/rolls back AND closes on PostgreSQL."""

    def __init__(self, raw):
        self.conn = raw

    def cursor(self, *args, **kwargs):
        return self.conn.cursor(*args, **kwargs)

    def commit(self):
        try:
            self.conn.commit()
        except Exception as e:
            logger.error("[DB] PostgreSQL commit failed: %s", e)
            raise

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception as e:
            logger.error("[DB] PostgreSQL rollback failed: %s", e)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def get_conn():
    """
    PostgreSQL when DATABASE_URL is set (raises DatabaseUnavailableError if unreachable —
    no silent fallback), otherwise SQLite at JARVIS_SQLITE_PATH.
    """
    global USING_SQLITE
    if DATABASE_URL:
        try:
            raw = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
                client_encoding="UTF8",
            )
        except Exception as e:
            logger.error("[DB] DATABASE_URL is configured but PostgreSQL is unreachable: %s", type(e).__name__)
            raise DatabaseUnavailableError(
                f"PostgreSQL configured (DATABASE_URL) but unreachable: {type(e).__name__}"
            ) from e
        USING_SQLITE = False
        return PGConnection(raw)
    USING_SQLITE = True
    return SQLiteConnection()


def _is_sqlite_conn(conn) -> bool:
    return isinstance(conn, SQLiteConnection)


def _rowcount(cur) -> int:
    rc = getattr(cur, "rowcount", 0)
    return rc if isinstance(rc, int) and rc > 0 else 0


def _count(row) -> int:
    if not row:
        return 0
    if isinstance(row, dict):
        return int(row.get("cnt") or 0)
    return int(row[0] or 0)


# Every table holding shop or customer data, with its shop column (used by purge_shop;
# tests verify this list covers every CREATE TABLE in init_db).
SHOP_TABLES: List[Tuple[str, str]] = [
    ("nonces", "shop"),
    ("messages", "shop"),
    ("briefings", "shop"),
    ("autopilot_logs", "shop"),
    ("shop_settings", "shop"),
    ("checkout_drip_states", "shop_domain"),
    ("post_delivery_automations", "shop_domain"),
    ("seo_automation_logs", "shop_domain"),
    ("marketing_consents", "shop_domain"),
    ("message_frequency_logs", "shop_domain"),
    ("suppression_list", "shop_domain"),
    ("app_state", "shop"),
    ("shops", "shop"),
]


def init_db():
    """Create all tables if they don't exist (idempotent; also migrates legacy consent rows)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shops (
                    id SERIAL PRIMARY KEY,
                    shop TEXT UNIQUE NOT NULL,
                    access_token TEXT NOT NULL,
                    shop_name TEXT,
                    plan TEXT DEFAULT 'trial',
                    trial_ends TIMESTAMP,
                    active BOOLEAN DEFAULT TRUE,
                    installed_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS nonces (
                    shop TEXT PRIMARY KEY,
                    nonce TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    shop TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS briefings (
                    id SERIAL PRIMARY KEY,
                    shop TEXT NOT NULL,
                    data JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS autopilot_logs (
                    id SERIAL PRIMARY KEY,
                    shop TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target_name TEXT,
                    target_email TEXT,
                    subject TEXT,
                    message TEXT,
                    revenue NUMERIC DEFAULT 0.0,
                    status TEXT DEFAULT 'executed',
                    checkout_id TEXT,
                    country TEXT,
                    lang TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );

                ALTER TABLE autopilot_logs ADD COLUMN IF NOT EXISTS checkout_id TEXT;
                ALTER TABLE autopilot_logs ADD COLUMN IF NOT EXISTS country TEXT;
                ALTER TABLE autopilot_logs ADD COLUMN IF NOT EXISTS lang TEXT;

                CREATE TABLE IF NOT EXISTS shop_settings (
                    shop TEXT PRIMARY KEY,
                    email_provider TEXT DEFAULT 'resend',
                    resend_api_key TEXT,
                    smtp_host TEXT DEFAULT 'smtp.gmail.com',
                    smtp_port INTEGER DEFAULT 587,
                    smtp_user TEXT,
                    smtp_password TEXT,
                    sender_email TEXT DEFAULT '',
                    sender_name TEXT DEFAULT 'Grozavu',
                    merchant_notify_email TEXT DEFAULT '',
                    notify_merchant_on_cart BOOLEAN DEFAULT TRUE,
                    updated_at TIMESTAMP DEFAULT NOW()
                );

                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS whatsapp_provider VARCHAR(32) DEFAULT 'auto';
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS whatsapp_api_token TEXT;
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id VARCHAR(64);
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS twilio_account_sid VARCHAR(64);
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS twilio_auth_token VARCHAR(64);
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS twilio_whatsapp_number VARCHAR(64) DEFAULT 'whatsapp:+14155238886';
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS whatsapp_webhook_url TEXT;

                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS telegram_bot_token VARCHAR(128);
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(64);
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS notify_telegram BOOLEAN DEFAULT FALSE;
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS discord_webhook_url TEXT;
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS notify_discord BOOLEAN DEFAULT FALSE;
                ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS merchant_notify_phone VARCHAR(64);

                CREATE TABLE IF NOT EXISTS checkout_drip_states (
                    id SERIAL PRIMARY KEY,
                    shop_domain TEXT NOT NULL,
                    checkout_id TEXT NOT NULL UNIQUE,
                    checkout_token TEXT,
                    email TEXT,
                    phone TEXT,
                    customer_name TEXT,
                    checkout_url TEXT NOT NULL,
                    total_price NUMERIC DEFAULT 0.0,
                    currency VARCHAR(16) DEFAULT 'EUR',
                    items JSONB DEFAULT '[]'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    current_stage INTEGER DEFAULT 0,
                    stage_1_sent_at TIMESTAMP WITH TIME ZONE,
                    stage_2_sent_at TIMESTAMP WITH TIME ZONE,
                    stage_3_sent_at TIMESTAMP WITH TIME ZONE,
                    status VARCHAR(32) DEFAULT 'active',
                    converted_at TIMESTAMP WITH TIME ZONE,
                    converted_order_id TEXT,
                    revenue_recovered NUMERIC DEFAULT 0.0,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_drip_states_active_cadence
                ON checkout_drip_states(shop_domain, status, current_stage, created_at);

                CREATE INDEX IF NOT EXISTS idx_drip_states_conversion_lookup
                ON checkout_drip_states(shop_domain, email, checkout_token);

                CREATE TABLE IF NOT EXISTS post_delivery_automations (
                    id SERIAL PRIMARY KEY,
                    shop_domain VARCHAR(255) NOT NULL,
                    order_id VARCHAR(64) NOT NULL UNIQUE,
                    order_number VARCHAR(64),
                    customer_email VARCHAR(255),
                    customer_phone VARCHAR(64),
                    customer_name VARCHAR(255),
                    fulfilled_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL,
                    items_summary JSONB DEFAULT '[]'::jsonb,
                    status VARCHAR(32) DEFAULT 'pending',
                    sent_at TIMESTAMP WITH TIME ZONE,
                    discount_code VARCHAR(32) DEFAULT 'MGVIP15',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_post_delivery_due
                ON post_delivery_automations(shop_domain, status, scheduled_for);

                CREATE INDEX IF NOT EXISTS idx_post_delivery_order
                ON post_delivery_automations(shop_domain, order_id);

                ALTER TABLE post_delivery_automations ADD COLUMN IF NOT EXISTS lang VARCHAR(8);

                CREATE TABLE IF NOT EXISTS seo_automation_logs (
                    id SERIAL PRIMARY KEY,
                    shop_domain TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    product_title TEXT,
                    change_type TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    applied_at TIMESTAMP DEFAULT NOW(),
                    status TEXT DEFAULT 'applied'
                );

                CREATE TABLE IF NOT EXISTS marketing_consents (
                    id SERIAL PRIMARY KEY,
                    shop_domain TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    accepts_marketing INTEGER DEFAULT 0,
                    opt_out_at TIMESTAMP,
                    source TEXT DEFAULT 'checkout',
                    channel TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );

                ALTER TABLE marketing_consents ADD COLUMN IF NOT EXISTS channel TEXT;

                CREATE INDEX IF NOT EXISTS idx_consents_email
                ON marketing_consents(shop_domain, channel, email);

                CREATE INDEX IF NOT EXISTS idx_consents_phone
                ON marketing_consents(shop_domain, channel, phone);

                CREATE TABLE IF NOT EXISTS message_frequency_logs (
                    id SERIAL PRIMARY KEY,
                    shop_domain TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    sequence_key TEXT,
                    sent_at TIMESTAMP DEFAULT NOW()
                );

                ALTER TABLE message_frequency_logs ADD COLUMN IF NOT EXISTS sequence_key TEXT;

                CREATE INDEX IF NOT EXISTS idx_frequency_recipient
                ON message_frequency_logs(shop_domain, recipient, sent_at);

                CREATE TABLE IF NOT EXISTS suppression_list (
                    id SERIAL PRIMARY KEY,
                    shop_domain TEXT NOT NULL,
                    identifier_hash TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    reason TEXT DEFAULT 'opt_out',
                    created_at TIMESTAMP DEFAULT NOW()
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_suppression_shop_hash
                ON suppression_list(shop_domain, identifier_hash);

                CREATE TABLE IF NOT EXISTS app_state (
                    shop TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (shop, key)
                );
            """)

            if not _is_sqlite_conn(conn):
                # New consent rows must never default to "consented".
                cur.execute("ALTER TABLE marketing_consents ALTER COLUMN accepts_marketing SET DEFAULT 0")

            _migrate_legacy_consents(cur)
        conn.commit()


def _migrate_legacy_consents(cur) -> int:
    """
    Legacy rows (channel IS NULL) mixed email+phone in one row and applied email
    consent to the phone. Split them: email rows keep only a denial/opt-out (a legacy
    grant is downgraded to unknown because the old code invented consent); a phone
    on such a row only carries an opt-out/denial forward; phone-only legacy
    "consent" is downgraded to unknown (it was never proven to be SMS consent).
    Idempotent: only touches rows whose channel is NULL.
    """
    cur.execute("""
        SELECT id, shop_domain, email, phone, accepts_marketing, opt_out_at, source
        FROM marketing_consents WHERE channel IS NULL
    """)
    rows = cur.fetchall() or []
    migrated = 0
    for r in rows:
        r = dict(r)
        e = normalize_email(r.get("email"))
        p = normalize_phone(r.get("phone"))
        opted = r.get("opt_out_at") is not None
        accepts = r.get("accepts_marketing")
        denied = opted or (accepts is not None and not accepts)
        if e:
            # Legacy "consent" was often invented (old code defaulted unknown consent to True),
            # so a legacy grant becomes UNKNOWN. Only denials/opt-outs are carried forward.
            # Real consent is re-recorded from Shopify on the next checkout/order sync.
            cur.execute(
                "UPDATE marketing_consents SET channel = 'email', email = %s, phone = NULL, accepts_marketing = %s WHERE id = %s",
                (e, 0 if denied else None, r["id"]),
            )
            if p and denied:
                cur.execute("""
                    INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, opt_out_at, source, channel, created_at, updated_at)
                    VALUES(%s, NULL, %s, 0, %s, %s, 'sms', NOW(), NOW())
                """, (r["shop_domain"], p, r.get("opt_out_at"), r.get("source") or "legacy"))
        elif p:
            new_accepts = 0 if denied else None
            cur.execute(
                "UPDATE marketing_consents SET channel = 'sms', phone = %s, accepts_marketing = %s WHERE id = %s",
                (p, new_accepts, r["id"]),
            )
        else:
            cur.execute("UPDATE marketing_consents SET channel = 'invalid' WHERE id = %s", (r["id"],))
        if opted:
            for kind, ident in (("email", e), ("phone", p)):
                if ident:
                    _add_suppression(cur, r["shop_domain"], ident, kind, "legacy_opt_out")
        migrated += 1
    return migrated


# ── Nonces ────────────────────────────────────────────────────────────────────

def store_nonce(shop: str, nonce: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nonces(shop, nonce, created_at) VALUES(%s, %s, %s) "
                "ON CONFLICT(shop) DO UPDATE SET nonce=%s, created_at=%s",
                (shop, nonce, _utc_naive(), nonce, _utc_naive())
            )
        conn.commit()


NONCE_TTL_MINUTES = 30


def store_nonce_fresh(shop: str, nonce: str) -> None:
    """store_nonce + drop OAuth nonces older than NONCE_TTL_MINUTES (keeps the table small)."""
    store_nonce(shop, nonce)
    cutoff = _utc_naive(datetime.now(timezone.utc) - timedelta(minutes=NONCE_TTL_MINUTES))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nonces WHERE created_at < %s AND shop <> %s", (cutoff, shop))
        conn.commit()


def verify_and_delete_nonce(shop: str, nonce: str) -> bool:
    """Constant-time compare; a nonce older than NONCE_TTL_MINUTES is rejected (and deleted)."""
    import hmac as _hmac
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nonce, created_at FROM nonces WHERE shop=%s", (shop,))
            row = cur.fetchone()
            if not row:
                return False
            created = row.get("created_at") if isinstance(row, dict) else None
            fresh = True
            if created is not None:
                if isinstance(created, str):
                    try:
                        created = datetime.fromisoformat(created.replace("Z", "").split(".")[0])
                    except ValueError:
                        created = None
                if isinstance(created, datetime):
                    created_utc = created.replace(tzinfo=None) if created.tzinfo is None else _utc_naive(created)
                    fresh = (_utc_naive() - created_utc) <= timedelta(minutes=NONCE_TTL_MINUTES)
            ok = fresh and _hmac.compare_digest(str(row["nonce"]).encode("utf-8"), str(nonce or "").encode("utf-8"))
            if ok or not fresh:
                cur.execute("DELETE FROM nonces WHERE shop=%s", (shop,))
                conn.commit()
            return ok


# ── Shops ─────────────────────────────────────────────────────────────────────

def _clean_shop(shop: Optional[str]) -> str:
    """Normalized shop domain; control characters (e.g. NUL, rejected by PostgreSQL) -> ''."""
    if not isinstance(shop, str):
        return ""
    clean = shop.strip().lower()
    if any(ord(ch) < 32 for ch in clean):
        return ""
    return clean


def upsert_shop(shop: str, access_token: str, shop_name: str = ""):
    """Insert or update a shop (re-install after uninstall re-activates it)."""
    clean = _clean_shop(shop)
    trial_ends = _utc_naive(datetime.now(timezone.utc) + timedelta(days=7))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shops(shop, access_token, shop_name, trial_ends, active)
                VALUES(%s, %s, %s, %s, TRUE)
                ON CONFLICT(shop) DO UPDATE SET
                    access_token=%s, shop_name=%s, active=TRUE, updated_at=NOW()
            """, (clean, access_token, shop_name, trial_ends, access_token, shop_name))
        conn.commit()


def get_shop(shop: str) -> Optional[Dict]:
    """Pure read: the active shop row for a normalized shop domain, or None."""
    clean_shop = _clean_shop(shop)
    if not clean_shop:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM shops WHERE shop=%s AND active=TRUE", (clean_shop,))
            row = cur.fetchone()
            return dict(row) if row else None


# ── Messages / Chat history ───────────────────────────────────────────────────

def save_message(shop: str, role: str, content: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages(shop, role, content) VALUES(%s, %s, %s)",
                (shop, role, content)
            )
        conn.commit()


def get_messages(shop: str, limit: int = 20) -> List[Dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, created_at FROM messages WHERE shop=%s ORDER BY created_at DESC, id DESC LIMIT %s",
                (shop, limit)
            )
            rows = cur.fetchall()
            return list(reversed([dict(r) for r in rows]))


# ── Briefings ─────────────────────────────────────────────────────────────────

def save_briefing(shop: str, data: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO briefings(shop, data) VALUES(%s, %s)",
                (shop, json.dumps(data))
            )
        conn.commit()


def get_latest_briefing(shop: str) -> Optional[Dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data, created_at FROM briefings WHERE shop=%s ORDER BY created_at DESC, id DESC LIMIT 1",
                (shop,)
            )
            row = cur.fetchone()
            if row:
                data = row["data"]
                if isinstance(data, (str, bytes)):
                    # SQLite stores JSON text; PostgreSQL JSONB is already decoded -> same shape on both.
                    try:
                        data = json.loads(data)
                    except (TypeError, ValueError):
                        pass
                return {"data": data, "created_at": str(row["created_at"])}
    return None


# ── Autopilot Logs & Automation Helpers ────────────────────────────────────────

def get_active_shops() -> List[Dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT shop, access_token, shop_name, plan FROM shops WHERE active=TRUE")
            return [dict(r) for r in cur.fetchall()]


def is_checkout_recently_processed(
    shop: str,
    checkout_id: Optional[str] = None,
    email: Optional[str] = None,
    hours: int = 48,
    now_dt: Optional[datetime] = None,
) -> bool:
    """Portable (SQLite + PostgreSQL): cutoff is computed in Python, no INTERVAL literal."""
    cid = str(checkout_id) if checkout_id else None
    clean_email = normalize_email(email)
    if not cid and not clean_email:
        return False
    cutoff = _utc_naive((now_dt or datetime.now(timezone.utc)) - timedelta(hours=int(hours)))

    conditions = []
    params: List[Any] = [shop, cutoff]
    if cid:
        conditions.append("checkout_id = %s")
        params.append(cid)
    if clean_email and "checkout" not in clean_email:
        conditions.append("LOWER(TRIM(target_email)) = %s")
        params.append(clean_email)
    if not conditions:
        return False

    query = f"""
        SELECT 1 AS hit FROM autopilot_logs
        WHERE shop = %s
          AND created_at >= %s
          AND ({' OR '.join(conditions)})
        LIMIT 1
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            return cur.fetchone() is not None


def save_autopilot_log(
    shop: str,
    action_type: str,
    target_name: str,
    target_email: str,
    subject: str,
    message: str,
    revenue: float = 0.0,
    status: str = "executed",
    checkout_id: Optional[str] = None,
    country: Optional[str] = None,
    lang: Optional[str] = None
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # created_at set in UTC from Python so time-window checks are identical on SQLite and
            # PostgreSQL regardless of the server session time zone.
            cur.execute("""
                INSERT INTO autopilot_logs (shop, action_type, target_name, target_email, subject, message, revenue, status, checkout_id, country, lang, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (shop, action_type, target_name, target_email, subject, message, revenue, status, checkout_id, country, lang, _utc_naive()))
        conn.commit()


def get_autopilot_logs(shop: str, limit: int = 20) -> List[Dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, action_type, target_name, target_email, subject, message, revenue, status, checkout_id, country, lang, created_at
                FROM autopilot_logs
                WHERE shop=%s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
            """, (shop, limit))
            rows = cur.fetchall()
            logs = []
            for r in rows:
                item = dict(r)
                item["created_at"] = str(item["created_at"])
                item["revenue"] = float(item.get("revenue") or 0.0)
                logs.append(item)
            return logs


# ── Shop Settings (Email & Notification Config) ───────────────────────────────

def get_shop_settings(shop: str) -> Dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM shop_settings WHERE shop=%s", (shop,))
            row = cur.fetchone()
            if row:
                res = dict(row)
                res["updated_at"] = str(res.get("updated_at") or "")
                if not res.get("whatsapp_provider"):
                    res["whatsapp_provider"] = "auto"
                if not res.get("twilio_whatsapp_number"):
                    res["twilio_whatsapp_number"] = "whatsapp:+14155238886"
                res["notify_telegram"] = bool(res.get("notify_telegram"))
                res["notify_discord"] = bool(res.get("notify_discord"))
                return res
            return {
                "shop": shop,
                "email_provider": "resend",
                "resend_api_key": "",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "",
                "smtp_password": "",
                # Empty -> EmailDispatcher falls back to env SENDER_EMAIL
                "sender_email": "",
                "sender_name": "Grozavu",
                "merchant_notify_email": os.getenv("MERCHANT_NOTIFY_EMAIL", ""),
                "notify_merchant_on_cart": True,
                # WhatsApp settings
                "whatsapp_provider": "auto",
                "whatsapp_api_token": "",
                "whatsapp_phone_number_id": "",
                "twilio_account_sid": "",
                "twilio_auth_token": "",
                "twilio_whatsapp_number": "whatsapp:+14155238886",
                "whatsapp_webhook_url": "",
                # Mobile notification settings
                "telegram_bot_token": "",
                "telegram_chat_id": "",
                "notify_telegram": False,
                "discord_webhook_url": "",
                "notify_discord": False,
                "merchant_notify_phone": os.getenv("MERCHANT_NOTIFY_PHONE", ""),
                "updated_at": ""
            }


def save_shop_settings(shop: str, s: Dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shop_settings (
                    shop, email_provider, resend_api_key, smtp_host, smtp_port,
                    smtp_user, smtp_password, sender_email, sender_name,
                    merchant_notify_email, notify_merchant_on_cart,
                    whatsapp_provider, whatsapp_api_token, whatsapp_phone_number_id,
                    twilio_account_sid, twilio_auth_token, twilio_whatsapp_number,
                    whatsapp_webhook_url,
                    telegram_bot_token, telegram_chat_id, notify_telegram,
                    discord_webhook_url, notify_discord,
                    merchant_notify_phone,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s, %s,
                    %s,
                    NOW()
                )
                ON CONFLICT(shop) DO UPDATE SET
                    email_provider=EXCLUDED.email_provider,
                    resend_api_key=EXCLUDED.resend_api_key,
                    smtp_host=EXCLUDED.smtp_host,
                    smtp_port=EXCLUDED.smtp_port,
                    smtp_user=EXCLUDED.smtp_user,
                    smtp_password=EXCLUDED.smtp_password,
                    sender_email=EXCLUDED.sender_email,
                    sender_name=EXCLUDED.sender_name,
                    merchant_notify_email=EXCLUDED.merchant_notify_email,
                    notify_merchant_on_cart=EXCLUDED.notify_merchant_on_cart,
                    whatsapp_provider=EXCLUDED.whatsapp_provider,
                    whatsapp_api_token=EXCLUDED.whatsapp_api_token,
                    whatsapp_phone_number_id=EXCLUDED.whatsapp_phone_number_id,
                    twilio_account_sid=EXCLUDED.twilio_account_sid,
                    twilio_auth_token=EXCLUDED.twilio_auth_token,
                    twilio_whatsapp_number=EXCLUDED.twilio_whatsapp_number,
                    whatsapp_webhook_url=EXCLUDED.whatsapp_webhook_url,
                    telegram_bot_token=EXCLUDED.telegram_bot_token,
                    telegram_chat_id=EXCLUDED.telegram_chat_id,
                    notify_telegram=EXCLUDED.notify_telegram,
                    discord_webhook_url=EXCLUDED.discord_webhook_url,
                    notify_discord=EXCLUDED.notify_discord,
                    merchant_notify_phone=EXCLUDED.merchant_notify_phone,
                    updated_at=NOW()
            """, (
                shop,
                s.get("email_provider", "resend"),
                s.get("resend_api_key", ""),
                s.get("smtp_host", "smtp.gmail.com"),
                int(s.get("smtp_port") or 587),
                s.get("smtp_user", ""),
                s.get("smtp_password", ""),
                s.get("sender_email", ""),
                s.get("sender_name", "Grozavu"),
                s.get("merchant_notify_email", os.getenv("MERCHANT_NOTIFY_EMAIL", "")),
                s.get("notify_merchant_on_cart", True),
                s.get("whatsapp_provider", "auto"),
                s.get("whatsapp_api_token", ""),
                s.get("whatsapp_phone_number_id", ""),
                s.get("twilio_account_sid", ""),
                s.get("twilio_auth_token", ""),
                s.get("twilio_whatsapp_number", "whatsapp:+14155238886"),
                s.get("whatsapp_webhook_url", ""),
                s.get("telegram_bot_token", ""),
                s.get("telegram_chat_id", ""),
                bool(s.get("notify_telegram", False)),
                s.get("discord_webhook_url", ""),
                bool(s.get("notify_discord", False)),
                s.get("merchant_notify_phone") or "",
            ))
        conn.commit()


# ── Checkout Drip States & Cadence Persistence ───────────────────────────────

def upsert_checkout_drip_state(shop: str, checkout: Dict) -> Dict:
    """
    Inserts a newly discovered checkout or updates existing record.
    Preserves converted/canceled terminal states (never reverts them to active).
    Email is stored normalized (strip+lower) so conversion matching works.
    """
    cid = str(checkout.get("id"))
    token = str(checkout.get("token") or "")
    email = normalize_email(checkout.get("email")) or ""
    phone = (checkout.get("phone") or "").strip() if isinstance(checkout.get("phone"), str) else str(checkout.get("phone") or "")
    c_name = (checkout.get("customer_name") or "").strip() if isinstance(checkout.get("customer_name"), str) else ""
    raw_url = checkout.get("checkout_url") or checkout.get("abandoned_checkout_url") or ""
    try:
        total_price = float(checkout.get("total_price") or 0.0)
    except (TypeError, ValueError):
        total_price = 0.0
    currency = checkout.get("currency") or "EUR"
    items_data = json.dumps(checkout.get("line_items") or checkout.get("items") or [])

    # Parse created_at safely to UTC
    raw_created = checkout.get("created_at")
    cart_created = None
    if isinstance(raw_created, str):
        try:
            cart_created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        except ValueError:
            cart_created = None
    elif isinstance(raw_created, datetime):
        cart_created = raw_created
    if cart_created is None:
        cart_created = datetime.now(timezone.utc)
    if cart_created.tzinfo is None:
        cart_created = cart_created.replace(tzinfo=timezone.utc)
    cart_created = cart_created.astimezone(timezone.utc)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO checkout_drip_states (
                    shop_domain, checkout_id, checkout_token, email, phone,
                    customer_name, checkout_url, total_price, currency, items,
                    created_at, current_stage, status, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 'active', NOW()
                )
                ON CONFLICT (checkout_id) DO UPDATE SET
                    checkout_url = EXCLUDED.checkout_url,
                    total_price = EXCLUDED.total_price,
                    items = EXCLUDED.items,
                    phone = COALESCE(NULLIF(EXCLUDED.phone, ''), checkout_drip_states.phone),
                    email = COALESCE(NULLIF(EXCLUDED.email, ''), checkout_drip_states.email),
                    updated_at = NOW()
                WHERE checkout_drip_states.status NOT IN ('converted', 'canceled')
                RETURNING *;
            """, (
                shop, cid, token, email, phone, c_name, raw_url,
                total_price, currency, items_data, cart_created
            ))
            row = cur.fetchone()
            if row:
                conn.commit()
                return dict(row)

            # If not returned due to WHERE condition (e.g. status was already converted), fetch existing
            cur.execute("SELECT * FROM checkout_drip_states WHERE checkout_id = %s", (cid,))
            existing = cur.fetchone()
            conn.commit()
            return dict(existing) if existing else {}


def get_checkout_drip_state(shop: str, checkout_id: str) -> Optional[Dict]:
    """Retrieve drip state record for a checkout."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM checkout_drip_states
                WHERE shop_domain = %s AND checkout_id = %s
            """, (shop, str(checkout_id)))
            row = cur.fetchone()
            return dict(row) if row else None


def get_active_drip_states(shop: Optional[str] = None) -> List[Dict]:
    """Retrieve all active checkouts that may be eligible for cadence evaluation."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if shop:
                cur.execute("""
                    SELECT * FROM checkout_drip_states
                    WHERE shop_domain = %s AND status = 'active' AND current_stage < 3
                    ORDER BY created_at ASC
                """, (shop,))
            else:
                cur.execute("""
                    SELECT * FROM checkout_drip_states
                    WHERE status = 'active' AND current_stage < 3
                    ORDER BY created_at ASC
                """)
            return [dict(r) for r in cur.fetchall()]


_VALID_STAGES = (1, 2, 3)


def _validate_stage(stage: Any) -> int:
    """Stage must be the int 1, 2 or 3 (or its digit string) — it is interpolated into a column name."""
    if isinstance(stage, bool):
        raise ValueError(f"Invalid drip stage: {stage!r}")
    if isinstance(stage, int):
        st = stage
    elif isinstance(stage, str) and stage.strip().isdigit():
        st = int(stage.strip())
    else:
        raise ValueError(f"Invalid drip stage: {stage!r}")
    if st not in _VALID_STAGES:
        raise ValueError(f"Invalid drip stage: {stage!r}")
    return st


def update_drip_stage(checkout_id: str, stage: int, sent_at: Optional[datetime] = None) -> bool:
    """
    Advance the stage of an ACTIVE checkout and record the stage dispatch timestamp.
    Never touches converted/canceled rows. Stage must be 1, 2 or 3.
    Returns True when a row was updated.
    """
    st = _validate_stage(stage)
    if sent_at is None:
        sent_at = datetime.now(timezone.utc)

    stage_col = f"stage_{st}_sent_at"
    # Stage 3 marks state as exhausted after sending
    status_clause = ", status = 'exhausted'" if st >= 3 else ""

    query = f"""
        UPDATE checkout_drip_states
        SET current_stage = %s, {stage_col} = %s, updated_at = NOW(){status_clause}
        WHERE checkout_id = %s AND status = 'active'
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (st, sent_at, str(checkout_id)))
            updated = _rowcount(cur) > 0
        conn.commit()
    return bool(updated)


def claim_drip_stage(
    checkout_id: str,
    expected_stage: int,
    new_stage: int,
    sent_at: Optional[datetime] = None,
) -> bool:
    """
    Atomic compare-and-set on checkout_drip_states.current_stage: moves an ACTIVE
    checkout from expected_stage to new_stage (and stamps stage_<new>_sent_at).
    Returns True only for the single caller that won the race.
    Status is left 'active' so a conversion during/after the send is still recorded.
    """
    new_st = _validate_stage(new_stage)
    exp = int(expected_stage)
    if exp < 0 or exp >= new_st:
        raise ValueError(f"expected_stage {expected_stage!r} must be lower than new_stage {new_stage!r}")
    stamp = sent_at or datetime.now(timezone.utc)
    query = f"""
        UPDATE checkout_drip_states
        SET current_stage = %s, stage_{new_st}_sent_at = %s, updated_at = NOW()
        WHERE checkout_id = %s AND current_stage = %s AND status = 'active'
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (new_st, stamp, str(checkout_id), exp))
            won = _rowcount(cur) == 1
        conn.commit()
    return bool(won)


def release_drip_stage(checkout_id: str, claimed_stage: int, previous_stage: int) -> bool:
    """
    Revert a claim (every channel failed): current_stage claimed -> previous and
    clears stage_<claimed>_sent_at. Only applies while the row is still active and
    still at the claimed stage. Returns True when reverted.
    """
    claimed = _validate_stage(claimed_stage)
    prev = int(previous_stage)
    if prev < 0 or prev >= claimed:
        raise ValueError(f"previous_stage {previous_stage!r} must be lower than claimed_stage {claimed_stage!r}")
    query = f"""
        UPDATE checkout_drip_states
        SET current_stage = %s, stage_{claimed}_sent_at = NULL, updated_at = NOW()
        WHERE checkout_id = %s AND current_stage = %s AND status = 'active'
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (prev, str(checkout_id), claimed))
            reverted = _rowcount(cur) == 1
        conn.commit()
    return bool(reverted)


def mark_drip_converted(
    shop: str,
    checkout_id: Optional[str] = None,
    email: Optional[str] = None,
    checkout_token: Optional[str] = None,
    order_id: Optional[str] = None,
    revenue: float = 0.0,
    return_attribution: bool = False,
) -> Union[int, Tuple[int, int]]:
    """
    Reconciles an order by marking matching active drip records as converted.
    Stops all pending stages. Returns number of rows updated
    (or (rows_updated, attributed_rows) with return_attribution=True).
    Email matching is normalized on both sides (handles legacy un-normalized rows).
    revenue_recovered is only credited to checkouts where Jarvis actually sent at least
    one stage (current_stage > 0) — otherwise the order is not a "recovery".
    """
    cid_str = str(checkout_id) if checkout_id else None
    token_str = str(checkout_token) if checkout_token else None
    email_clean = normalize_email(email)

    conditions = []
    match_params: List[Any] = []
    if cid_str:
        conditions.append("checkout_id = %s")
        match_params.append(cid_str)
    if token_str:
        conditions.append("checkout_token = %s")
        match_params.append(token_str)
    if email_clean:
        conditions.append("(LOWER(TRIM(email)) = %s AND email != '')")
        match_params.append(email_clean)
    if not conditions:
        return (0, 0) if return_attribution else 0

    try:
        rev = float(revenue or 0.0)
    except (TypeError, ValueError):
        rev = 0.0

    where = f"shop_domain = %s AND status = 'active' AND ({' OR '.join(conditions)})"
    with get_conn() as conn:
        with conn.cursor() as cur:
            attributed = 0
            if return_attribution:
                cur.execute(
                    f"SELECT COUNT(*) AS cnt FROM checkout_drip_states WHERE {where} AND current_stage > 0",
                    tuple([shop] + match_params),
                )
                attributed = _count(cur.fetchone())
            cur.execute(f"""
                UPDATE checkout_drip_states
                SET status = 'converted',
                    converted_at = NOW(),
                    converted_order_id = %s,
                    revenue_recovered = CASE WHEN current_stage > 0 THEN %s ELSE 0 END,
                    updated_at = NOW()
                WHERE {where}
            """, tuple([str(order_id or ""), rev, shop] + match_params))
            rows_updated = cur.rowcount
        conn.commit()
    if return_attribution:
        return rows_updated, attributed
    return rows_updated


def mark_drip_exhausted(checkout_id: str) -> bool:
    """Marks checkout as exhausted when cadence window (>72h) has expired."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE checkout_drip_states
                SET status = 'exhausted', updated_at = NOW()
                WHERE checkout_id = %s AND status = 'active'
            """, (str(checkout_id),))
        conn.commit()
    return True


# ── Post-Delivery VIP Automations Persistence ────────────────────────────────

def enqueue_post_delivery_automation(
    shop: str = "",
    order_id: str = "",
    order_number: str = "",
    customer_email: Optional[str] = None,
    customer_phone: Optional[str] = None,
    customer_name: Optional[str] = None,
    fulfilled_at: Optional[datetime] = None,
    scheduled_for: Optional[datetime] = None,
    items_summary: Any = None,
    discount_code: str = "MGVIP15",
    order_data: Optional[Dict[str, Any]] = None,
    shop_domain: Optional[str] = None,
    lang: Optional[str] = None,
) -> bool:
    """
    Enqueues a fulfilled order into post_delivery_automations for the VIP thank-you.
    Idempotent on order_id. Does not overwrite already sent or canceled automations.
    """
    target_shop = shop_domain or shop
    if order_data and isinstance(order_data, dict):
        target_shop = target_shop or order_data.get("shop_domain") or order_data.get("shop") or ""
        order_id = str(order_data.get("order_id") or order_data.get("id") or order_id)
        order_number = str(order_data.get("order_number") or order_data.get("name") or order_id).lstrip("#")
        customer = order_data.get("customer") or {}
        first = customer.get("first_name", "") if isinstance(customer, dict) else ""
        last = customer.get("last_name", "") if isinstance(customer, dict) else ""
        customer_name = customer_name or (f"{first} {last}".strip() or order_data.get("customer_name") or "")
        customer_email = customer_email or order_data.get("customer_email") or order_data.get("email") or (customer.get("email") if isinstance(customer, dict) else None)
        customer_phone = customer_phone or order_data.get("customer_phone") or order_data.get("phone") or (customer.get("phone") if isinstance(customer, dict) else None)
        raw_f = order_data.get("fulfilled_at")
        if raw_f and fulfilled_at is None:
            if isinstance(raw_f, str):
                fulfilled_at = datetime.fromisoformat(raw_f.replace("Z", "+00:00"))
            elif isinstance(raw_f, datetime):
                fulfilled_at = raw_f
        raw_s = order_data.get("scheduled_for")
        if raw_s and scheduled_for is None:
            if isinstance(raw_s, str):
                scheduled_for = datetime.fromisoformat(raw_s.replace("Z", "+00:00"))
            elif isinstance(raw_s, datetime):
                scheduled_for = raw_s
        items_summary = items_summary if items_summary is not None else (order_data.get("items_summary") or order_data.get("line_items"))

    if not fulfilled_at:
        fulfilled_at = datetime.now(timezone.utc)
    elif fulfilled_at.tzinfo is None:
        fulfilled_at = fulfilled_at.replace(tzinfo=timezone.utc)

    if not scheduled_for:
        scheduled_for = fulfilled_at + timedelta(days=5)
    elif scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

    items_json = json.dumps(items_summary) if isinstance(items_summary, (list, dict)) else json.dumps([])
    clean_phone = (customer_phone or "").strip() if isinstance(customer_phone, str) else (str(customer_phone) if customer_phone else "")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO post_delivery_automations (
                    shop_domain, order_id, order_number, customer_email,
                    customer_phone, customer_name, fulfilled_at, scheduled_for,
                    items_summary, status, discount_code, lang, created_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s::jsonb, 'pending', %s, %s, NOW()
                )
                ON CONFLICT (order_id) DO NOTHING
            """, (
                target_shop, str(order_id), str(order_number or "").lstrip("#"),
                normalize_email(customer_email),
                clean_phone or None,
                (customer_name or "").strip(),
                fulfilled_at, scheduled_for, items_json,
                discount_code or "MGVIP15",
                (lang or None),
            ))
            inserted = cur.rowcount > 0
        conn.commit()
    return inserted


def get_due_post_delivery_automations(
    shop: Optional[str] = None,
    now_dt: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Retrieve pending post-delivery automations where scheduled_for <= now_dt."""
    now = now_dt or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if shop:
                cur.execute("""
                    SELECT * FROM post_delivery_automations
                    WHERE shop_domain = %s
                      AND status = 'pending'
                      AND scheduled_for <= %s
                    ORDER BY scheduled_for ASC
                """, (shop, now))
            else:
                cur.execute("""
                    SELECT * FROM post_delivery_automations
                    WHERE status = 'pending'
                      AND scheduled_for <= %s
                    ORDER BY scheduled_for ASC
                """, (now,))
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def mark_post_delivery_sent(
    order_id: Union[int, str],
    sent_at: Optional[datetime] = None
) -> bool:
    """Marks a post-delivery automation record as 'sent' with timestamp."""
    sent = sent_at or datetime.now(timezone.utc)
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)

    # Match the Shopify order id only: a short numeric order id must never hit another row's serial id.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE post_delivery_automations
                SET status = 'sent', sent_at = %s
                WHERE order_id = %s AND status = 'pending'
            """, (sent, str(order_id)))
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def mark_post_delivery_automation_sent(
    automation_id: Union[int, str],
    channel: Optional[str] = None,
    sent_at: Optional[datetime] = None
) -> bool:
    """Alias for mark_post_delivery_sent."""
    return mark_post_delivery_sent(order_id=automation_id, sent_at=sent_at)


def reschedule_post_delivery(order_id: Union[int, str], scheduled_for: datetime) -> bool:
    """Move a still-pending thank-you to a new time (e.g. once the carrier reports delivery)."""
    when = scheduled_for if scheduled_for.tzinfo else scheduled_for.replace(tzinfo=timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE post_delivery_automations
                SET scheduled_for = %s
                WHERE order_id = %s AND status = 'pending'
            """, (when, str(order_id)))
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def mark_post_delivery_status(order_id: Union[int, str], status: str) -> bool:
    """
    Terminal non-sent outcome for a pending automation, e.g. 'suppressed'
    (no consent / opted out / no reachable channel) or 'expired'.
    """
    clean_status = (status or "").strip().lower()
    if clean_status not in ("suppressed", "expired", "failed", "canceled"):
        raise ValueError(f"Unsupported post-delivery status: {status!r}")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE post_delivery_automations
                SET status = %s
                WHERE order_id = %s AND status = 'pending'
            """, (clean_status, str(order_id)))
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def cancel_post_delivery_automation(order_id: str) -> bool:
    """Cancels any pending post-delivery automation for an order (e.g. on refund or cancel)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE post_delivery_automations
                SET status = 'canceled'
                WHERE order_id = %s AND status = 'pending'
            """, (str(order_id),))
            canceled = cur.rowcount > 0
        conn.commit()
    return canceled


def get_post_delivery_queue(shop: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve post-delivery automations queue for a shop."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM post_delivery_automations
                WHERE shop_domain = %s
                ORDER BY scheduled_for DESC
                LIMIT %s
            """, (shop, limit))
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def get_post_delivery_automation(order_id: str) -> Optional[Dict[str, Any]]:
    """Helper to inspect post delivery record by order_id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM post_delivery_automations WHERE order_id = %s", (str(order_id),))
            row = cur.fetchone()
            return dict(row) if row else None


# ── SEO Automation Logs ────────────────────────────────────────────────────────

def log_seo_change(
    shop_domain: str,
    product_id: str,
    product_title: str,
    change_type: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    status: str = "applied"
) -> bool:
    """Log an on-store product SEO change (or proposal, via status)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO seo_automation_logs(shop_domain, product_id, product_title, change_type, old_value, new_value, status, applied_at)
                VALUES(%s, %s, %s, %s, %s, %s, %s, NOW())
            """, (shop_domain, str(product_id), product_title, change_type, old_value or "", new_value or "", status))
        conn.commit()
    return True


def get_seo_logs(shop_domain: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve history of SEO changes for a shop."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM seo_automation_logs
                WHERE shop_domain = %s
                ORDER BY applied_at DESC, id DESC
                LIMIT %s
            """, (shop_domain, limit))
            rows = cur.fetchall()
            return [dict(r) for r in rows]


# ── Marketing Consent, Suppression & Frequency Caps ──────────────────────────

CONSENT_GRANTED = "granted"
CONSENT_DENIED = "denied"
CONSENT_OPTED_OUT = "opted_out"
CONSENT_UNKNOWN = "unknown"

PHONE_CHANNELS = ("sms", "whatsapp", "phone", "wa")

# Sources allowed to lift a previous explicit opt-out (a fresh, explicit re-subscription).
# Automated syncs ('checkout', 'order', ...) can never undo an opt-out.
RESUBSCRIBE_SOURCES = ("resubscribe", "double_opt_in", "customer_request")


def _consent_kind(channel: Optional[str]) -> Optional[str]:
    if channel is None:
        return None
    c = str(channel).strip().lower()
    if c in PHONE_CHANNELS:
        return "sms"
    if c == "email":
        return "email"
    return None


def _add_suppression(cur, shop_domain: str, normalized_ident: str, kind: str, reason: str = "opt_out"):
    if not normalized_ident:
        return
    cur.execute("""
        INSERT INTO suppression_list(shop_domain, identifier_hash, kind, reason, created_at)
        VALUES(%s, %s, %s, %s, NOW())
        ON CONFLICT (shop_domain, identifier_hash) DO NOTHING
    """, (shop_domain, identity_hash(normalized_ident), kind, reason))


def _is_suppressed_cur(cur, shop_domain: str, normalized_ident: Optional[str]) -> bool:
    if not normalized_ident:
        return False
    cur.execute(
        "SELECT 1 AS hit FROM suppression_list WHERE shop_domain = %s AND identifier_hash = %s LIMIT 1",
        (shop_domain, identity_hash(normalized_ident)),
    )
    return cur.fetchone() is not None


def is_suppressed(shop_domain: str, email: Optional[str] = None, phone: Optional[str] = None) -> bool:
    """True if the (normalized) email or phone is on the hashed suppression list for this shop."""
    e = normalize_email(email)
    p = normalize_phone(phone)
    if not e and not p:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            return _is_suppressed_cur(cur, shop_domain, e) or _is_suppressed_cur(cur, shop_domain, p)


def _upsert_consent_row(cur, shop_domain: str, kind: str, ident: str, accepts: bool, source: str) -> bool:
    col = "email" if kind == "email" else "phone"
    cur.execute(f"""
        SELECT id, accepts_marketing, opt_out_at FROM marketing_consents
        WHERE shop_domain = %s AND {col} = %s AND (channel = %s OR channel IS NULL)
        ORDER BY id DESC
    """, (shop_domain, ident, kind))
    rows = [dict(r) for r in (cur.fetchall() or [])]
    opted_out = any(r.get("opt_out_at") is not None for r in rows) or _is_suppressed_cur(cur, shop_domain, ident)
    resubscribe = bool(accepts) and source in RESUBSCRIBE_SOURCES

    if accepts and opted_out and not resubscribe:
        # Opt-out always wins over automated consent syncs.
        return False

    if resubscribe and opted_out:
        cur.execute(
            "DELETE FROM suppression_list WHERE shop_domain = %s AND identifier_hash = %s",
            (shop_domain, identity_hash(ident)),
        )

    if rows:
        if resubscribe:
            cur.execute(f"""
                UPDATE marketing_consents
                SET accepts_marketing = %s, opt_out_at = NULL, source = %s, channel = %s, updated_at = NOW()
                WHERE shop_domain = %s AND {col} = %s AND (channel = %s OR channel IS NULL)
            """, (1, source, kind, shop_domain, ident, kind))
        else:
            cur.execute(f"""
                UPDATE marketing_consents
                SET accepts_marketing = %s, source = %s, channel = %s, updated_at = NOW()
                WHERE shop_domain = %s AND {col} = %s AND (channel = %s OR channel IS NULL)
            """, (1 if accepts else 0, source, kind, shop_domain, ident, kind))
    else:
        cur.execute("""
            INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, source, channel, created_at, updated_at)
            VALUES(%s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (
            shop_domain,
            ident if kind == "email" else None,
            ident if kind == "sms" else None,
            1 if accepts else 0,
            source,
            kind,
        ))
    return True


def record_marketing_consent(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    accepts_marketing: Optional[Any] = None,
    source: str = "checkout",
    sms_accepts_marketing: Optional[Any] = None,
    channel: Optional[str] = None,
) -> bool:
    """
    Record a customer's marketing consent. Tri-state: True / False / None
    (None == unknown -> nothing is written; unknown is never turned into consent).

    - email + accepts_marketing            -> email consent (keyed by normalized email)
    - phone only + accepts_marketing       -> SMS/WhatsApp consent (keyed by normalized phone)
    - channel="sms"/"whatsapp"             -> accepts_marketing refers to the phone
    - sms_accepts_marketing                -> SMS/WhatsApp consent for `phone`
    Email consent is NEVER applied to the phone. A previous explicit opt-out is never
    lifted by an automated source (see RESUBSCRIBE_SOURCES).
    Returns True if at least one consent row was written.
    """
    e = normalize_email(email)
    p = normalize_phone(phone)
    email_val = _to_tristate(accepts_marketing)
    sms_val = _to_tristate(sms_accepts_marketing)
    kind = _consent_kind(channel)
    src = (source or "checkout").strip().lower()

    writes: List[Tuple[str, str, bool]] = []
    if kind == "sms":
        if p and email_val is not None and sms_val is None:
            sms_val = email_val
        email_val = None
    elif kind is None and not e and p and email_val is not None and sms_val is None:
        # Called separately for the phone identity.
        sms_val = email_val
        email_val = None

    if e and email_val is not None:
        writes.append(("email", e, email_val))
    if p and sms_val is not None:
        writes.append(("sms", p, sms_val))
    if not writes:
        return False

    written = False
    with get_conn() as conn:
        with conn.cursor() as cur:
            for w_kind, ident, val in writes:
                if _upsert_consent_row(cur, shop_domain, w_kind, ident, bool(val), src):
                    written = True
        conn.commit()
    return written


def record_opt_out(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    source: str = "unsubscribe_link",
) -> bool:
    """
    Record an unsubscribe / opt-out request (email link, List-Unsubscribe POST,
    WhatsApp STOP...). Writes the opt-out on the consent rows AND a hashed
    suppression entry, so it survives redaction. Returns True if recorded.
    """
    e = normalize_email(email)
    p = normalize_phone(phone)
    if not e and not p:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            for kind, col, ident in (("email", "email", e), ("sms", "phone", p)):
                if not ident:
                    continue
                cur.execute(f"""
                    UPDATE marketing_consents
                    SET accepts_marketing = 0, opt_out_at = NOW(), updated_at = NOW(), channel = %s
                    WHERE shop_domain = %s AND {col} = %s AND (channel = %s OR channel IS NULL)
                """, (kind, shop_domain, ident, kind))
                if _rowcount(cur) == 0:
                    cur.execute("""
                        INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, opt_out_at, source, channel, created_at, updated_at)
                        VALUES(%s, %s, %s, 0, NOW(), %s, %s, NOW(), NOW())
                    """, (
                        shop_domain,
                        ident if kind == "email" else None,
                        ident if kind == "sms" else None,
                        source or "unsubscribe_link",
                        kind,
                    ))
                _add_suppression(cur, shop_domain, ident, "email" if kind == "email" else "phone", "opt_out")
        conn.commit()
    return True


def lift_opt_out(shop_domain: str, email: Optional[str] = None, phone: Optional[str] = None) -> bool:
    """
    Undo an opt-out at the customer's explicit request (merchant action). Removes the suppression
    entry and the opt-out mark; consent goes back to UNKNOWN (never "granted"): the next consent
    Shopify reports for that customer decides again. Returns True if anything changed.
    """
    e = normalize_email(email)
    p = normalize_phone(phone)
    if not e and not p:
        return False
    changed = False
    with get_conn() as conn:
        with conn.cursor() as cur:
            for kind, col, ident in (("email", "email", e), ("sms", "phone", p)):
                if not ident:
                    continue
                cur.execute(
                    "DELETE FROM suppression_list WHERE shop_domain = %s AND identifier_hash = %s",
                    (shop_domain, identity_hash(ident)),
                )
                changed = _rowcount(cur) > 0 or changed
                cur.execute(f"""
                    UPDATE marketing_consents
                    SET opt_out_at = NULL, accepts_marketing = NULL, source = 'opt_out_lifted', updated_at = NOW()
                    WHERE shop_domain = %s AND {col} = %s AND (channel = %s OR channel IS NULL)
                      AND opt_out_at IS NOT NULL
                """, (shop_domain, ident, kind))
                changed = _rowcount(cur) > 0 or changed
        conn.commit()
    return changed


def get_consent_status(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    channel: Optional[str] = None,
) -> str:
    """
    'granted' | 'denied' | 'opted_out' | 'unknown' for ONE identity:
    channel 'email' -> email, channel 'sms'/'whatsapp' -> phone,
    channel None -> email if given, else phone.
    """
    kind = _consent_kind(channel)
    e = normalize_email(email)
    p = normalize_phone(phone)
    if kind is None:
        kind = "email" if e else "sms"
    ident = e if kind == "email" else p
    if not ident:
        return CONSENT_UNKNOWN
    col = "email" if kind == "email" else "phone"

    with get_conn() as conn:
        with conn.cursor() as cur:
            if _is_suppressed_cur(cur, shop_domain, ident):
                return CONSENT_OPTED_OUT
            cur.execute(f"""
                SELECT accepts_marketing, opt_out_at, channel FROM marketing_consents
                WHERE shop_domain = %s AND {col} = %s AND (channel = %s OR channel IS NULL)
                ORDER BY id DESC
            """, (shop_domain, ident, kind))
            rows = [dict(r) for r in (cur.fetchall() or [])]

    if any(r.get("opt_out_at") is not None for r in rows):
        return CONSENT_OPTED_OUT
    # Legacy (channel NULL) rows can grant email consent, never SMS/WhatsApp consent.
    granting = [r for r in rows if r.get("channel") == kind or (kind == "email" and r.get("channel") is None)]
    if not granting:
        if any(r.get("accepts_marketing") is not None and not r.get("accepts_marketing") for r in rows):
            return CONSENT_DENIED
        return CONSENT_UNKNOWN
    latest = granting[0].get("accepts_marketing")
    if latest is None:
        return CONSENT_UNKNOWN
    return CONSENT_GRANTED if bool(latest) else CONSENT_DENIED


def is_consent_given(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    channel: Optional[str] = None,
) -> bool:
    """
    True ONLY when explicit marketing consent is recorded for that identity and it is
    not opted out / suppressed. Unknown consent == no consent (returns False).
    """
    return get_consent_status(shop_domain, email=email, phone=phone, channel=channel) == CONSENT_GRANTED


def normalize_recipient(recipient: Optional[str], channel: Optional[str] = "email") -> Optional[str]:
    """Normalize a frequency-log recipient by channel (email -> email key, else phone key)."""
    if recipient is None:
        return None
    raw = str(recipient)
    kind = _consent_kind(channel)
    if kind == "email" or (kind is None and "@" in raw):
        return normalize_email(raw)
    if "@" in raw:
        return normalize_email(raw)
    return normalize_phone(raw)


# Per-sequence maximums by sequence_key prefix ("cart:<checkout_id>", "vip:<order_id>").
SEQUENCE_LIMITS: Dict[str, int] = {"cart": 3, "vip": 1}
DEFAULT_SEQUENCE_LIMIT = 1
MAX_MARKETING_PER_30D = 4
NEW_SEQUENCE_COOLDOWN_HOURS = 72


def sequence_limit_for(sequence_key: Optional[str]) -> int:
    if not sequence_key:
        return DEFAULT_SEQUENCE_LIMIT
    prefix = str(sequence_key).split(":", 1)[0].strip().lower()
    return SEQUENCE_LIMITS.get(prefix, DEFAULT_SEQUENCE_LIMIT)


def get_message_counts(
    shop_domain: str,
    recipient: str,
    channel: str = "email",
    sequence_key: Optional[str] = None,
    now_dt: Optional[datetime] = None,
    related_recipients: Optional[Iterable[Optional[str]]] = None,
    message_type: Optional[str] = None,
) -> Dict[str, int]:
    """
    Counts of logged marketing messages.
    Per identity (this email OR this phone): last_72h, last_30d, sequence_total (legacy keys).
    Per PERSON (this identity + related identities, e.g. the same customer's email and phone):
      - person_sequence_total: messages of this sequence on any channel
      - person_other_72h: messages of OTHER sequences (or un-keyed) in the last 72h
      - person_touches_30d: distinct touches in 30 days; one touch = one (sequence, step),
        so the same step sent by email AND WhatsApp counts once
      - touch_exists: this (sequence, step) was already sent on another channel
    """
    ident = normalize_recipient(recipient, channel)
    if not ident:
        return {"last_72h": 0, "last_30d": 0, "sequence_total": 0, "person_sequence_total": 0,
                "person_other_72h": 0, "person_touches_30d": 0, "touch_exists": 0}
    idents = [ident]
    for r in related_recipients or []:
        if not r:
            continue
        rid = normalize_email(r) if "@" in str(r) else normalize_phone(r)
        if rid and rid not in idents:
            idents.append(rid)
    now = _utc_naive(now_dt)
    cutoff_72 = now - timedelta(hours=NEW_SEQUENCE_COOLDOWN_HOURS)
    cutoff_30d = now - timedelta(days=30)
    in_sql = ", ".join(["%s"] * len(idents))
    seq = str(sequence_key) if sequence_key else None
    touch_expr = "COALESCE(sequence_key, 'id:' || CAST(id AS TEXT)) || '|' || message_type"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM message_frequency_logs
                WHERE shop_domain = %s AND recipient = %s AND sent_at > %s
            """, (shop_domain, ident, cutoff_72))
            c72 = _count(cur.fetchone())
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM message_frequency_logs
                WHERE shop_domain = %s AND recipient = %s AND sent_at > %s
            """, (shop_domain, ident, cutoff_30d))
            c30 = _count(cur.fetchone())
            cur.execute(f"""
                SELECT COUNT(DISTINCT {touch_expr}) AS cnt FROM message_frequency_logs
                WHERE shop_domain = %s AND recipient IN ({in_sql}) AND sent_at > %s
            """, (shop_domain, *idents, cutoff_30d))
            touches = _count(cur.fetchone())
            if seq:
                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM message_frequency_logs
                    WHERE shop_domain = %s AND recipient IN ({in_sql}) AND sent_at > %s
                      AND (sequence_key IS NULL OR sequence_key <> %s)
                """, (shop_domain, *idents, cutoff_72, seq))
            else:
                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM message_frequency_logs
                    WHERE shop_domain = %s AND recipient IN ({in_sql}) AND sent_at > %s
                """, (shop_domain, *idents, cutoff_72))
            other72 = _count(cur.fetchone())
            seq_ident = seq_person = touch_exists = 0
            if seq:
                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM message_frequency_logs
                    WHERE shop_domain = %s AND recipient = %s AND sequence_key = %s
                """, (shop_domain, ident, seq))
                seq_ident = _count(cur.fetchone())
                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM message_frequency_logs
                    WHERE shop_domain = %s AND recipient IN ({in_sql}) AND sequence_key = %s
                """, (shop_domain, *idents, seq))
                seq_person = _count(cur.fetchone())
                if message_type:
                    cur.execute(f"""
                        SELECT COUNT(*) AS cnt FROM message_frequency_logs
                        WHERE shop_domain = %s AND recipient IN ({in_sql}) AND sequence_key = %s AND message_type = %s
                    """, (shop_domain, *idents, seq, str(message_type)))
                    touch_exists = _count(cur.fetchone())
    return {"last_72h": c72, "last_30d": c30, "sequence_total": seq_ident,
            "person_sequence_total": seq_person, "person_other_72h": other72,
            "person_touches_30d": touches, "touch_exists": touch_exists}


def can_send_message_frequency(
    shop_domain: str,
    recipient: str,
    channel: str = "email",
    max_per_72h: int = 1,
    max_per_30d: int = MAX_MARKETING_PER_30D,
    sequence_key: Optional[str] = None,
    max_per_sequence: Optional[int] = None,
    now_dt: Optional[datetime] = None,
    related_recipients: Optional[Iterable[Optional[str]]] = None,
    message_type: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Frequency policy, counted PER PERSON (pass the customer's other identities in
    `related_recipients`, e.g. their phone when checking their email):
    - per sequence and channel: cart:<id> max 3, vip:<id> max 1 (other prefixes 1);
    - max 4 marketing touches per person per rolling 30 days (one step sent on both
      email and WhatsApp is ONE touch);
    - a NEW sequence (or an un-keyed message) is blocked if the person got any message
      from another sequence in the last 72h. Follow-ups of a started sequence are exempt.
    """
    ident = normalize_recipient(recipient, channel)
    if not ident:
        return False, "Recipient empty"

    counts = get_message_counts(shop_domain, ident, channel=channel, sequence_key=sequence_key, now_dt=now_dt,
                                related_recipients=related_recipients, message_type=message_type)

    if sequence_key:
        limit = max_per_sequence if max_per_sequence is not None else sequence_limit_for(sequence_key)
        if counts["sequence_total"] >= limit:
            return False, f"Frequency cap: sequence {sequence_key} already has {counts['sequence_total']}/{limit} messages"

    new_touch = not (sequence_key and message_type and counts["touch_exists"] > 0)
    if new_touch and counts["person_touches_30d"] >= max_per_30d:
        return False, f"Frequency cap: {counts['person_touches_30d']} marketing messages to this customer in the last 30 days (max {max_per_30d})"

    is_followup = bool(sequence_key) and counts["person_sequence_total"] > 0
    if not is_followup and counts["person_other_72h"] >= max_per_72h:
        return False, f"Frequency cap: customer got {counts['person_other_72h']} message(s) in the last 72 hours (new sequence blocked)"

    return True, "OK"


def record_message_sent(
    shop_domain: str,
    recipient: str,
    channel: str,
    message_type: str,
    sequence_key: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> bool:
    """Record a dispatched marketing message for frequency cap tracking (normalized recipient)."""
    ident = normalize_recipient(recipient, channel)
    if not ident:
        return False
    stamp = _utc_naive(sent_at)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO message_frequency_logs(shop_domain, recipient, channel, message_type, sequence_key, sent_at)
                VALUES(%s, %s, %s, %s, %s, %s)
            """, (shop_domain, ident, channel, message_type, str(sequence_key) if sequence_key else None, stamp))
        conn.commit()
    return True


def get_consent_stats(shop_domain: str) -> Dict[str, int]:
    """Return summary of consent and messaging metrics for dashboard."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_recorded,
                    SUM(CASE WHEN accepts_marketing = 1 AND opt_out_at IS NULL THEN 1 ELSE 0 END) as active_subscribers,
                    SUM(CASE WHEN opt_out_at IS NOT NULL OR accepts_marketing = 0 THEN 1 ELSE 0 END) as unsubscribed,
                    SUM(CASE WHEN channel = 'email' AND accepts_marketing = 1 AND opt_out_at IS NULL THEN 1 ELSE 0 END) as email_subscribers,
                    SUM(CASE WHEN channel = 'sms' AND accepts_marketing = 1 AND opt_out_at IS NULL THEN 1 ELSE 0 END) as sms_subscribers
                FROM marketing_consents
                WHERE shop_domain = %s
            """, (shop_domain,))
            row = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS cnt FROM suppression_list WHERE shop_domain = %s", (shop_domain,))
            suppressed = _count(cur.fetchone())
            if row:
                r = dict(row)
                return {
                    "total_recorded": int(r.get("total_recorded") or 0),
                    "active_subscribers": int(r.get("active_subscribers") or 0),
                    "unsubscribed": int(r.get("unsubscribed") or 0),
                    "email_subscribers": int(r.get("email_subscribers") or 0),
                    "sms_subscribers": int(r.get("sms_subscribers") or 0),
                    "suppressed": suppressed,
                }
    return {"total_recorded": 0, "active_subscribers": 0, "unsubscribed": 0,
            "email_subscribers": 0, "sms_subscribers": 0, "suppressed": 0}


# ── App state (heartbeat, alerts, weekly report bookkeeping) ─────────────────

def get_state(shop: str, key: str) -> Optional[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM app_state WHERE shop = %s AND key = %s", (shop, key))
            row = cur.fetchone()
            return (row.get("value") if isinstance(row, dict) else row[0]) if row else None


def set_state(shop: str, key: str, value: Optional[str]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_state(shop, key, value, updated_at) VALUES(%s, %s, %s, NOW())
                ON CONFLICT(shop, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (shop, key, value))
        conn.commit()


def weekly_report_data(shop: str, since: datetime, until: Optional[datetime] = None) -> Dict[str, Any]:
    """Real numbers for the merchant's weekly report (nothing estimated)."""
    start = _utc_naive(since)
    end = _utc_naive(until)
    out: Dict[str, Any] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM autopilot_logs
                WHERE shop = %s AND created_at >= %s AND created_at < %s
                  AND status LIKE 'stage_%%_sent%%'
            """, (shop, start, end))
            out["cart_messages_sent"] = _count(cur.fetchone())
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM autopilot_logs
                WHERE shop = %s AND created_at >= %s AND created_at < %s AND status LIKE 'stage_%%_failed'
            """, (shop, start, end))
            out["cart_messages_failed"] = _count(cur.fetchone())
            since_aware = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
            until_aware = until or datetime.now(timezone.utc)
            if until_aware.tzinfo is None:
                until_aware = until_aware.replace(tzinfo=timezone.utc)
            cur.execute("""
                SELECT COUNT(*) AS cnt, COALESCE(SUM(revenue_recovered), 0) AS rev FROM checkout_drip_states
                WHERE shop_domain = %s AND status = 'converted' AND current_stage > 0
                  AND converted_at >= %s AND converted_at < %s
            """, (shop, since_aware, until_aware))
            row = cur.fetchone() or {}
            row = dict(row) if row else {}
            out["recovered_orders"] = int(row.get("cnt") or 0)
            out["recovered_revenue"] = round(float(row.get("rev") or 0.0), 2)
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM autopilot_logs
                WHERE shop = %s AND created_at >= %s AND created_at < %s AND status LIKE 'vip_sent_%%'
            """, (shop, start, end))
            out["vip_thank_yous_sent"] = _count(cur.fetchone())
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM marketing_consents
                WHERE shop_domain = %s AND opt_out_at >= %s AND opt_out_at < %s
            """, (shop, start, end))
            out["opt_outs"] = _count(cur.fetchone())
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM marketing_consents
                WHERE shop_domain = %s AND opt_out_at >= %s AND opt_out_at < %s
                  AND source IN ('resend_bounce', 'resend_complaint')
            """, (shop, start, end))
            out["bounces_and_complaints"] = _count(cur.fetchone())
    return out


# ── GDPR: export / redact customer, purge shop ───────────────────────────────

def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value


def _row_jsonable(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _jsonable(v) for k, v in dict(row).items()}


def _text_mentions(value: Any, needle: Optional[str]) -> bool:
    if not needle or value is None:
        return False
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return needle in text.lower()


def _collect_customer_rows(cur, shop: str, e: Optional[str], p: Optional[str],
                           order_ids: Optional[Iterable[Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Find every row holding this customer's data in this shop (matching is normalized in Python)."""
    order_set = {str(o) for o in (order_ids or []) if o is not None and str(o) != ""}
    found: Dict[str, List[Dict[str, Any]]] = {}

    def match_email(v):
        return bool(e) and normalize_email(v) == e

    def match_phone(v):
        return bool(p) and normalize_phone(v) == p

    cur.execute("SELECT * FROM checkout_drip_states WHERE shop_domain = %s", (shop,))
    drips = [dict(r) for r in (cur.fetchall() or []) if match_email(r.get("email")) or match_phone(r.get("phone"))]
    found["checkout_drip_states"] = drips
    checkout_ids = {str(r.get("checkout_id")) for r in drips if r.get("checkout_id")}

    cur.execute("SELECT * FROM post_delivery_automations WHERE shop_domain = %s", (shop,))
    found["post_delivery_automations"] = [
        dict(r) for r in (cur.fetchall() or [])
        if match_email(r.get("customer_email")) or match_phone(r.get("customer_phone")) or str(r.get("order_id")) in order_set
    ]

    cur.execute("SELECT * FROM autopilot_logs WHERE shop = %s", (shop,))
    found["autopilot_logs"] = [
        dict(r) for r in (cur.fetchall() or [])
        if match_email(r.get("target_email")) or match_phone(r.get("target_email"))
        or (r.get("checkout_id") and str(r.get("checkout_id")) in checkout_ids)
    ]

    cur.execute("SELECT * FROM marketing_consents WHERE shop_domain = %s", (shop,))
    found["marketing_consents"] = [
        dict(r) for r in (cur.fetchall() or []) if match_email(r.get("email")) or match_phone(r.get("phone"))
    ]

    cur.execute("SELECT * FROM message_frequency_logs WHERE shop_domain = %s", (shop,))
    found["message_frequency_logs"] = [
        dict(r) for r in (cur.fetchall() or []) if (e and r.get("recipient") == e) or (p and r.get("recipient") == p)
    ]

    # Free text written by/for the merchant that may quote the customer's email.
    cur.execute("SELECT * FROM messages WHERE shop = %s", (shop,))
    found["messages"] = [dict(r) for r in (cur.fetchall() or []) if _text_mentions(r.get("content"), e)]

    cur.execute("SELECT * FROM briefings WHERE shop = %s", (shop,))
    found["briefings"] = [dict(r) for r in (cur.fetchall() or []) if _text_mentions(r.get("data"), e)]
    return found


def export_customer_data(shop: str, email: Optional[str] = None, phone: Optional[str] = None,
                         order_ids: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """GDPR data request: every stored row for this customer in this shop (JSON-serializable)."""
    e = normalize_email(email)
    p = normalize_phone(phone)
    if not e and not p and not order_ids:
        return {"ok": False, "reason": "no_identifier", "shop": shop, "data": {}}
    with get_conn() as conn:
        with conn.cursor() as cur:
            found = _collect_customer_rows(cur, shop, e, p, order_ids)
            suppressed = _is_suppressed_cur(cur, shop, e) or _is_suppressed_cur(cur, shop, p)
    data = {table: [_row_jsonable(r) for r in rows] for table, rows in found.items()}
    return {
        "ok": True,
        "shop": shop,
        "email": e,
        "phone": p,
        "suppressed": bool(suppressed),
        "consent": {
            "email": get_consent_status(shop, email=e, channel="email") if e else CONSENT_UNKNOWN,
            "sms": get_consent_status(shop, phone=p, channel="sms") if p else CONSENT_UNKNOWN,
        },
        "data": data,
        "counts": {table: len(rows) for table, rows in data.items()},
    }


def _delete_ids(cur, table: str, ids: List[Any]) -> int:
    deleted = 0
    ids = [i for i in ids if i is not None]
    for start in range(0, len(ids), 200):
        chunk = ids[start:start + 200]
        placeholders = ", ".join(["%s"] * len(chunk))
        cur.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(chunk))
        deleted += _rowcount(cur)
    return deleted


def redact_customer(shop: str, email: Optional[str] = None, phone: Optional[str] = None,
                    order_ids: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """
    GDPR customers/redact: delete this customer's PII rows in this shop from every table.
    If the customer had opted out, a hashed (sha256 of the normalized identifier)
    suppression entry is kept so they stay suppressed after redaction.
    """
    e = normalize_email(email)
    p = normalize_phone(phone)
    if not e and not p and not order_ids:
        return {"ok": False, "reason": "no_identifier", "shop": shop, "deleted": {}, "suppression_kept": False}

    deleted: Dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            found = _collect_customer_rows(cur, shop, e, p, order_ids)

            # Keep (or create) suppression entries for identities that had opted out.
            kept = False
            for kind, ident in (("email", e), ("phone", p)):
                if not ident:
                    continue
                had_opt_out = any(
                    r.get("opt_out_at") is not None and (
                        normalize_email(r.get("email")) == ident if kind == "email" else normalize_phone(r.get("phone")) == ident
                    )
                    for r in found.get("marketing_consents", [])
                )
                if had_opt_out:
                    _add_suppression(cur, shop, ident, kind, "opt_out_redacted")
                if had_opt_out or _is_suppressed_cur(cur, shop, ident):
                    kept = True

            for table, rows in found.items():
                deleted[table] = _delete_ids(cur, table, [r.get("id") for r in rows])
        conn.commit()
    return {"ok": True, "shop": shop, "deleted": deleted, "suppression_kept": kept}


def purge_shop(shop: str) -> Dict[str, Any]:
    """GDPR shop/redact (48h after uninstall): delete every table's rows for this shop."""
    clean = _clean_shop(shop)
    if not clean:
        return {"ok": False, "reason": "no_shop", "deleted": {}}
    deleted: Dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for table, col in SHOP_TABLES:
                cur.execute(f"DELETE FROM {table} WHERE {col} = %s", (clean,))
                deleted[table] = _rowcount(cur)
        conn.commit()
    return {"ok": True, "shop": clean, "deleted": deleted}

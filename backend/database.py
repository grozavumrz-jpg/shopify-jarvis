import os
import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timezone, timedelta

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("DATABASE_PUBLIC_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("POSTGRESQL_URL")
    or ""
)

import sqlite3
import re
import json

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "jarvis.db")
USING_SQLITE = False

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
        clean_sql = clean_sql.replace('%s', '?')

        statements = [s.strip() for s in clean_sql.split(';') if s.strip()]
        for stmt in statements:
            if params is not None and len(statements) == 1:
                clean_params = []
                for p in params:
                    if isinstance(p, (dict, list)):
                        clean_params.append(json.dumps(p))
                    elif isinstance(p, bool):
                        clean_params.append(1 if p else 0)
                    else:
                        clean_params.append(p)
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
    def __init__(self, db_path=SQLITE_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def cursor(self):
        return SQLiteCursor(self.conn.cursor())

    def commit(self):
        try:
            self.conn.commit()
        except Exception:
            pass

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
        finally:
            self.close()


def get_conn():
    global USING_SQLITE
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
            USING_SQLITE = False
            return conn
        except Exception:
            USING_SQLITE = True
            return SQLiteConnection()
    USING_SQLITE = True
    return SQLiteConnection()


def init_db():
    """Create all tables if they don't exist."""
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
                    sender_email TEXT DEFAULT 'onboarding@resend.dev',
                    sender_name TEXT DEFAULT 'Grozavu',
                    merchant_notify_email TEXT DEFAULT 'grozavumrz@gmail.com',
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
                    accepts_marketing INTEGER DEFAULT 1,
                    opt_out_at TIMESTAMP,
                    source TEXT DEFAULT 'checkout',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS message_frequency_logs (
                    id SERIAL PRIMARY KEY,
                    shop_domain TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # Seed default store maisongrozavu.myshopify.com
            cur.execute("""
                INSERT INTO shops(shop, access_token, shop_name, plan, active)
                VALUES(%s, %s, %s, %s, TRUE)
                ON CONFLICT(shop) DO UPDATE SET
                    plan = 'pro',
                    shop_name = 'Maison Grozavu',
                    active = TRUE
            """, ("maisongrozavu.myshopify.com", os.getenv("SHOPIFY_ACCESS_TOKEN", "shpat_live_token"), "Maison Grozavu", "pro"))

            # Seed default shop settings for Maison Grozavu
            cur.execute("""
                INSERT INTO shop_settings(shop, sender_name, sender_email, merchant_notify_email, notify_merchant_on_cart)
                VALUES(%s, %s, %s, %s, TRUE)
                ON CONFLICT(shop) DO UPDATE SET
                    sender_name = 'Maison Grozavu',
                    sender_email = 'contact@maisongrozavu.com',
                    merchant_notify_email = 'grozavumrz@gmail.com'
            """, ("maisongrozavu.myshopify.com", "Maison Grozavu", "contact@maisongrozavu.com", "grozavumrz@gmail.com"))
        conn.commit()


# ── Nonces ────────────────────────────────────────────────────────────────────

def store_nonce(shop: str, nonce: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nonces(shop, nonce) VALUES(%s, %s) ON CONFLICT(shop) DO UPDATE SET nonce=%s",
                (shop, nonce, nonce)
            )
        conn.commit()


def verify_and_delete_nonce(shop: str, nonce: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nonce FROM nonces WHERE shop=%s", (shop,))
            row = cur.fetchone()
            if row and row["nonce"] == nonce:
                cur.execute("DELETE FROM nonces WHERE shop=%s", (shop,))
                conn.commit()
                return True
    return False


# ── Shops ─────────────────────────────────────────────────────────────────────

def upsert_shop(shop: str, access_token: str, shop_name: str = ""):
    from datetime import timedelta
    trial_ends = datetime.utcnow() + timedelta(days=7)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shops(shop, access_token, shop_name, trial_ends)
                VALUES(%s, %s, %s, %s)
                ON CONFLICT(shop) DO UPDATE SET
                    access_token=%s, shop_name=%s, updated_at=NOW()
            """, (shop, access_token, shop_name, trial_ends, access_token, shop_name))
        conn.commit()


def get_shop(shop: str) -> Optional[Dict]:
    clean_shop = (shop or "").strip().lower()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM shops WHERE shop=%s AND active=TRUE", (clean_shop,))
            row = cur.fetchone()
            if row:
                return dict(row)
            if "maisongrozavu" in clean_shop:
                cur.execute("""
                    INSERT INTO shops(shop, access_token, shop_name, plan, active)
                    VALUES(%s, %s, %s, %s, TRUE)
                    ON CONFLICT(shop) DO UPDATE SET plan='pro', active=TRUE
                """, (clean_shop, os.getenv("SHOPIFY_ACCESS_TOKEN", "shpat_live_token"), "Maison Grozavu", "pro"))
                conn.commit()
                cur.execute("SELECT * FROM shops WHERE shop=%s AND active=TRUE", (clean_shop,))
                row2 = cur.fetchone()
                return dict(row2) if row2 else {
                    "shop": clean_shop,
                    "access_token": "shpat_live_token",
                    "shop_name": "Maison Grozavu",
                    "plan": "pro",
                    "active": True
                }
            return None


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
                "SELECT role, content, created_at FROM messages WHERE shop=%s ORDER BY created_at DESC LIMIT %s",
                (shop, limit)
            )
            rows = cur.fetchall()
            return list(reversed([dict(r) for r in rows]))


# ── Briefings ─────────────────────────────────────────────────────────────────

def save_briefing(shop: str, data: dict):
    import json
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
                "SELECT data, created_at FROM briefings WHERE shop=%s ORDER BY created_at DESC LIMIT 1",
                (shop,)
            )
            row = cur.fetchone()
            if row:
                return {"data": row["data"], "created_at": str(row["created_at"])}
    return None


# ── Autopilot Logs & Automation Helpers ────────────────────────────────────────

def get_active_shops() -> List[Dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT shop, access_token, shop_name, plan FROM shops WHERE active=TRUE")
            return [dict(r) for r in cur.fetchall()]


def is_checkout_recently_processed(shop: str, checkout_id: Optional[str] = None, email: Optional[str] = None, hours: int = 48) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT 1 FROM autopilot_logs
                WHERE shop = %s
                  AND created_at >= NOW() - INTERVAL '%s hours'
                  AND (
                      (%s IS NOT NULL AND checkout_id = %s)
                      OR
                      (%s IS NOT NULL AND target_email = %s AND target_email != '' AND target_email NOT LIKE '%%checkout%%')
                  )
                LIMIT 1
            """
            cur.execute(query, (shop, hours, checkout_id, checkout_id, email, email))
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
            cur.execute("""
                INSERT INTO autopilot_logs (shop, action_type, target_name, target_email, subject, message, revenue, status, checkout_id, country, lang)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (shop, action_type, target_name, target_email, subject, message, revenue, status, checkout_id, country, lang))
        conn.commit()


def get_autopilot_logs(shop: str, limit: int = 20) -> List[Dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, action_type, target_name, target_email, subject, message, revenue, status, checkout_id, country, lang, created_at
                FROM autopilot_logs
                WHERE shop=%s
                ORDER BY created_at DESC
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
                "sender_email": "onboarding@resend.dev",
                "sender_name": "Grozavu",
                "merchant_notify_email": "grozavumrz@gmail.com",
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
                    updated_at=NOW()
            """, (
                shop,
                s.get("email_provider", "resend"),
                s.get("resend_api_key", ""),
                s.get("smtp_host", "smtp.gmail.com"),
                int(s.get("smtp_port") or 587),
                s.get("smtp_user", ""),
                s.get("smtp_password", ""),
                s.get("sender_email", "onboarding@resend.dev"),
                s.get("sender_name", "Grozavu"),
                s.get("merchant_notify_email", "grozavumrz@gmail.com"),
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
                bool(s.get("notify_discord", False))
            ))
        conn.commit()


# ── Checkout Drip States & Cadence Persistence ───────────────────────────────

def upsert_checkout_drip_state(shop: str, checkout: Dict) -> Dict:
    """
    Inserts a newly discovered checkout or updates existing record.
    Preserves converted/canceled terminal states (never reverts them to active).
    """
    import json
    from datetime import datetime, timezone

    cid = str(checkout.get("id"))
    token = str(checkout.get("token") or "")
    email = checkout.get("email") or ""
    phone = checkout.get("phone") or ""
    c_name = checkout.get("customer_name") or "Client"
    raw_url = checkout.get("checkout_url") or checkout.get("abandoned_checkout_url") or ""
    total_price = float(checkout.get("total_price") or 0.0)
    currency = checkout.get("currency") or "EUR"
    items_data = json.dumps(checkout.get("line_items") or checkout.get("items") or [])
    
    # Parse created_at safely to UTC
    raw_created = checkout.get("created_at")
    if isinstance(raw_created, str):
        cart_created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
    elif isinstance(raw_created, datetime):
        cart_created = raw_created if raw_created.tzinfo else raw_created.replace(tzinfo=timezone.utc)
    else:
        cart_created = datetime.now(timezone.utc)

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


def update_drip_stage(checkout_id: str, stage: int, sent_at: Optional[datetime] = None) -> bool:
    """Advance the stage of a checkout and record stage dispatch timestamp."""
    from datetime import datetime, timezone
    if sent_at is None:
        sent_at = datetime.now(timezone.utc)

    stage_col = f"stage_{stage}_sent_at"
    # Stage 3 marks state as exhausted after sending
    status_clause = ", status = 'exhausted'" if stage >= 3 else ""

    query = f"""
        UPDATE checkout_drip_states
        SET current_stage = %s, {stage_col} = %s, updated_at = NOW(){status_clause}
        WHERE checkout_id = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (stage, sent_at, str(checkout_id)))
        conn.commit()
    return True


def mark_drip_converted(
    shop: str,
    checkout_id: Optional[str] = None,
    email: Optional[str] = None,
    checkout_token: Optional[str] = None,
    order_id: Optional[str] = None,
    revenue: float = 0.0
) -> int:
    """
    Reconciles an order by marking matching active drip records as converted.
    Stops all pending stages. Returns number of rows updated.
    """
    cid_str = str(checkout_id) if checkout_id else None
    token_str = str(checkout_token) if checkout_token else None
    email_clean = email.strip().lower() if email else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE checkout_drip_states
                SET status = 'converted',
                    converted_at = NOW(),
                    converted_order_id = %s,
                    revenue_recovered = %s,
                    updated_at = NOW()
                WHERE shop_domain = %s
                  AND status = 'active'
                  AND (
                      (%s IS NOT NULL AND checkout_id = %s)
                      OR (%s IS NOT NULL AND checkout_token = %s)
                      OR (%s IS NOT NULL AND LOWER(email) = %s AND email != '')
                  )
            """, (str(order_id or ""), revenue, shop, cid_str, cid_str, token_str, token_str, email_clean, email_clean))
            rows_updated = cur.rowcount
        conn.commit()
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
    shop_domain: Optional[str] = None
) -> bool:
    """
    Enqueues a fulfilled order into post_delivery_automations for VIP review & upsell.
    Idempotent on order_id. Does not overwrite already sent or canceled automations.
    """
    import json
    from datetime import datetime, timezone, timedelta

    target_shop = shop_domain or shop
    if order_data and isinstance(order_data, dict):
        target_shop = target_shop or order_data.get("shop_domain") or order_data.get("shop") or ""
        order_id = str(order_data.get("order_id") or order_data.get("id") or order_id)
        order_number = str(order_data.get("order_number") or order_data.get("name") or order_id).lstrip("#")
        customer = order_data.get("customer") or {}
        first = customer.get("first_name", "") if isinstance(customer, dict) else ""
        last = customer.get("last_name", "") if isinstance(customer, dict) else ""
        customer_name = customer_name or (f"{first} {last}".strip() or order_data.get("customer_name") or "Client")
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

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO post_delivery_automations (
                    shop_domain, order_id, order_number, customer_email,
                    customer_phone, customer_name, fulfilled_at, scheduled_for,
                    items_summary, status, discount_code, created_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s::jsonb, 'pending', %s, NOW()
                )
                ON CONFLICT (order_id) DO NOTHING
            """, (
                target_shop, str(order_id), str(order_number or "").lstrip("#"),
                (customer_email or "").strip() or None,
                (customer_phone or "").strip() or None,
                (customer_name or "Client").strip(),
                fulfilled_at, scheduled_for, items_json,
                discount_code or "MGVIP15"
            ))
            inserted = cur.rowcount > 0
        conn.commit()
    return inserted


def get_due_post_delivery_automations(
    shop: Optional[str] = None,
    now_dt: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Retrieve pending post-delivery automations where scheduled_for <= now_dt."""
    from datetime import datetime, timezone
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
    from datetime import datetime, timezone
    sent = sent_at or datetime.now(timezone.utc)
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if isinstance(order_id, int) or str(order_id).isdigit():
                cur.execute("""
                    UPDATE post_delivery_automations
                    SET status = 'sent', sent_at = %s
                    WHERE (id = %s OR order_id = %s) AND status = 'pending'
                """, (sent, int(order_id), str(order_id)))
            else:
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
    """Log an automated on-store product SEO change."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO seo_automation_logs(shop_domain, product_id, product_title, change_type, old_value, new_value, status, applied_at)
                VALUES(%s, %s, %s, %s, %s, %s, %s, NOW())
            """, (shop_domain, str(product_id), product_title, change_type, old_value or "", new_value or "", status))
        conn.commit()
    return True


def get_seo_logs(shop_domain: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve history of automated SEO changes for a shop."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM seo_automation_logs
                WHERE shop_domain = %s
                ORDER BY applied_at DESC
                LIMIT %s
            """, (shop_domain, limit))
            rows = cur.fetchall()
            return [dict(r) for r in rows]


# ── Marketing Consent & Frequency Caps ────────────────────────────────────────

def record_marketing_consent(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    accepts_marketing: bool = True,
    source: str = "checkout"
) -> bool:
    """Record or update a customer's marketing consent."""
    clean_email = email.strip().lower() if email else None
    clean_phone = phone.strip() if phone else None
    if not clean_email and not clean_phone:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            if clean_email:
                cur.execute("SELECT id FROM marketing_consents WHERE shop_domain = %s AND email = %s", (shop_domain, clean_email))
            else:
                cur.execute("SELECT id FROM marketing_consents WHERE shop_domain = %s AND phone = %s", (shop_domain, clean_phone))
            existing = cur.fetchone()

            if existing:
                e_id = existing["id"] if isinstance(existing, dict) else existing[0]
                cur.execute("""
                    UPDATE marketing_consents
                    SET accepts_marketing = %s, updated_at = NOW()
                    WHERE id = %s
                """, (1 if accepts_marketing else 0, e_id))
            else:
                cur.execute("""
                    INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, source, created_at, updated_at)
                    VALUES(%s, %s, %s, %s, %s, NOW(), NOW())
                """, (shop_domain, clean_email, clean_phone, 1 if accepts_marketing else 0, source))
        conn.commit()
    return True


def record_opt_out(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None
) -> bool:
    """Record an unsubscribe / opt-out request."""
    clean_email = email.strip().lower() if email else None
    clean_phone = phone.strip() if phone else None
    if not clean_email and not clean_phone:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            if clean_email:
                cur.execute("SELECT id FROM marketing_consents WHERE shop_domain = %s AND email = %s", (shop_domain, clean_email))
            else:
                cur.execute("SELECT id FROM marketing_consents WHERE shop_domain = %s AND phone = %s", (shop_domain, clean_phone))
            existing = cur.fetchone()

            if existing:
                e_id = existing["id"] if isinstance(existing, dict) else existing[0]
                cur.execute("""
                    UPDATE marketing_consents
                    SET accepts_marketing = 0, opt_out_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                """, (e_id,))
            else:
                cur.execute("""
                    INSERT INTO marketing_consents(shop_domain, email, phone, accepts_marketing, opt_out_at, source, created_at, updated_at)
                    VALUES(%s, %s, %s, 0, NOW(), 'unsubscribe_link', NOW(), NOW())
                """, (shop_domain, clean_email, clean_phone))
        conn.commit()
    return True


def is_consent_given(
    shop_domain: str,
    email: Optional[str] = None,
    phone: Optional[str] = None
) -> bool:
    """
    Check if marketing consent is active.
    Returns False if customer explicitly opted out.
    """
    clean_email = email.strip().lower() if email else None
    clean_phone = phone.strip() if phone else None
    if not clean_email and not clean_phone:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            if clean_email:
                cur.execute("""
                    SELECT accepts_marketing, opt_out_at FROM marketing_consents
                    WHERE shop_domain = %s AND email = %s
                    ORDER BY id DESC LIMIT 1
                """, (shop_domain, clean_email))
            else:
                cur.execute("""
                    SELECT accepts_marketing, opt_out_at FROM marketing_consents
                    WHERE shop_domain = %s AND phone = %s
                    ORDER BY id DESC LIMIT 1
                """, (shop_domain, clean_phone))
            row = cur.fetchone()
            if row:
                r_dict = dict(row)
                if r_dict.get("opt_out_at"):
                    return False
                return bool(r_dict.get("accepts_marketing"))
    return True


def can_send_message_frequency(
    shop_domain: str,
    recipient: str,
    channel: str = "email",
    max_per_72h: int = 1,
    max_per_30d: int = 3
) -> tuple[bool, str]:
    """
    Enforce frequency caps:
    - Max 1 marketing message per 72 hours
    - Max 3 marketing messages per 30 days
    """
    clean_recip = (recipient or "").strip().lower()
    if not clean_recip:
        return False, "Recipient empty"

    cutoff_72 = datetime.now(timezone.utc) - timedelta(hours=72)
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Check 72h window
            cur.execute("""
                SELECT COUNT(*) as cnt FROM message_frequency_logs
                WHERE shop_domain = %s AND recipient = %s AND sent_at >= %s
            """, (shop_domain, clean_recip, cutoff_72))
            row_72 = cur.fetchone()
            cnt_72 = row_72["cnt"] if isinstance(row_72, dict) else (row_72[0] if row_72 else 0)

            if cnt_72 >= max_per_72h:
                return False, f"Frequency cap: sent {cnt_72} messages in last 72 hours"

            # Check 30d window
            cur.execute("""
                SELECT COUNT(*) as cnt FROM message_frequency_logs
                WHERE shop_domain = %s AND recipient = %s AND sent_at >= %s
            """, (shop_domain, clean_recip, cutoff_30d))
            row_30 = cur.fetchone()
            cnt_30 = row_30["cnt"] if isinstance(row_30, dict) else (row_30[0] if row_30 else 0)

            if cnt_30 >= max_per_30d:
                return False, f"Frequency cap: sent {cnt_30} messages in last 30 days"

    return True, "OK"


def record_message_sent(
    shop_domain: str,
    recipient: str,
    channel: str,
    message_type: str
) -> bool:
    """Record a dispatched marketing message for frequency cap tracking."""
    clean_recip = (recipient or "").strip().lower()
    if not clean_recip:
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO message_frequency_logs(shop_domain, recipient, channel, message_type, sent_at)
                VALUES(%s, %s, %s, %s, NOW())
            """, (shop_domain, clean_recip, channel, message_type))
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
                    SUM(CASE WHEN opt_out_at IS NOT NULL OR accepts_marketing = 0 THEN 1 ELSE 0 END) as unsubscribed
                FROM marketing_consents
                WHERE shop_domain = %s
            """, (shop_domain,))
            row = cur.fetchone()
            if row:
                r = dict(row)
                return {
                    "total_recorded": int(r.get("total_recorded") or 0),
                    "active_subscribers": int(r.get("active_subscribers") or 0),
                    "unsubscribed": int(r.get("unsubscribed") or 0),
                }
    return {"total_recorded": 0, "active_subscribers": 0, "unsubscribed": 0}




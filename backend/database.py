import os
import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


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
            """)
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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM shops WHERE shop=%s AND active=TRUE", (shop,))
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
                "notify_merchant_on_cart": True
            }


def save_shop_settings(shop: str, s: Dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shop_settings (
                    shop, email_provider, resend_api_key, smtp_host, smtp_port,
                    smtp_user, smtp_password, sender_email, sender_name,
                    merchant_notify_email, notify_merchant_on_cart, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                s.get("notify_merchant_on_cart", True)
            ))
        conn.commit()


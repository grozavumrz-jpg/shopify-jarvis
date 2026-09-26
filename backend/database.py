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

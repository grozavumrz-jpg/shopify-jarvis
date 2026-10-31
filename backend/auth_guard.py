"""
Request authentication for Jarvis.

A protected route accepts EITHER:
  1. `Authorization: Bearer <Shopify session token>` — added automatically by
     App Bridge (app-bridge.js) when the dashboard runs embedded in Shopify
     admin. Verified with HS256 + SHOPIFY_API_SECRET, aud == SHOPIFY_API_KEY.
     The shop is taken from the token (`dest`), never from the request.
  2. `X-Jarvis-Key: <JARVIS_ADMIN_KEY>` — for the owner opening the dashboard
     directly (outside Shopify admin). Set JARVIS_ADMIN_KEY on Render.

Shopify webhooks are verified separately with `verify_webhook_hmac`.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request

SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
MIN_ADMIN_KEY_LEN = 12
TOKEN_LEEWAY_SECONDS = 10


def normalize_shop(shop: Optional[str]) -> Optional[str]:
    """Return a canonical `<name>.myshopify.com` or None if the value is not a valid shop domain."""
    if not shop:
        return None
    s = str(shop).strip().lower()
    s = re.sub(r"^https?://", "", s).split("/")[0].split("?")[0]
    if s and "." not in s:
        s = f"{s}.myshopify.com"
    return s if SHOP_RE.match(s) else None


def default_shop() -> str:
    return normalize_shop(os.getenv("SHOP_DOMAIN")) or "grozavushop.myshopify.com"  # real myshopify domain of maisongrozavu.com


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify_session_token(token: str, api_key: Optional[str] = None, api_secret: Optional[str] = None,
                         now: Optional[float] = None) -> Optional[dict]:
    """Verify a Shopify App Bridge session (ID) token. Returns the payload (with `_shop`) or None."""
    api_key = api_key if api_key is not None else os.getenv("SHOPIFY_API_KEY", "")
    api_secret = api_secret if api_secret is not None else os.getenv("SHOPIFY_API_SECRET", "")
    if not token or not api_key or not api_secret:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(parts[0]))
        if header.get("alg") != "HS256":
            return None
        expected = hmac.new(api_secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(parts[2])):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception:
        return None

    t = time.time() if now is None else now
    try:
        if float(payload.get("exp", 0)) < t - TOKEN_LEEWAY_SECONDS:
            return None
        if float(payload.get("nbf", 0)) > t + TOKEN_LEEWAY_SECONDS:
            return None
    except (TypeError, ValueError):
        return None

    aud = payload.get("aud")
    if (aud if isinstance(aud, list) else [aud]).count(api_key) == 0:
        return None

    dest_host = urlparse(str(payload.get("dest") or "")).hostname or str(payload.get("dest") or "")
    iss_host = urlparse(str(payload.get("iss") or "")).hostname
    if iss_host and dest_host and iss_host != dest_host:
        return None
    shop = normalize_shop(dest_host)
    if not shop:
        return None
    payload["_shop"] = shop
    return payload


@dataclass
class AuthContext:
    method: str               # "session_token" | "admin_key"
    shop: Optional[str] = None  # set for session tokens: the only shop this caller may touch


def _admin_key() -> str:
    key = os.getenv("JARVIS_ADMIN_KEY", "")
    return key if len(key) >= MIN_ADMIN_KEY_LEN else ""


async def require_auth(request: Request) -> AuthContext:
    """FastAPI dependency: 401 unless a valid admin key or Shopify session token is present."""
    admin_key = _admin_key()
    provided = request.headers.get("x-jarvis-key", "")
    if admin_key and provided and hmac.compare_digest(provided.encode(), admin_key.encode()):
        return AuthContext(method="admin_key")

    authz = request.headers.get("authorization", "")
    if authz[:7].lower() == "bearer ":
        payload = verify_session_token(authz[7:].strip())
        if payload:
            return AuthContext(method="session_token", shop=payload["_shop"])

    raise HTTPException(status_code=401, detail="auth_required")


def resolve_shop(auth: AuthContext, requested: Optional[str]) -> str:
    """Pick the shop a request may act on. Session tokens are pinned to their own shop."""
    if requested:
        norm = normalize_shop(requested)
        if not norm:
            raise HTTPException(status_code=400, detail="invalid_shop_domain")
    else:
        norm = None
    if auth.shop:
        if norm and norm != auth.shop:
            raise HTTPException(status_code=403, detail="shop_mismatch")
        return auth.shop
    return norm or default_shop()


def verify_webhook_hmac(raw_body: bytes, header_hmac: Optional[str], secret: Optional[str] = None) -> bool:
    """Shopify webhook signature: base64(HMAC-SHA256(secret, raw body))."""
    secret = secret if secret is not None else os.getenv("SHOPIFY_API_SECRET", "")
    if not secret or not header_hmac:
        return False
    digest = base64.b64encode(hmac.new(secret.encode(), raw_body or b"", hashlib.sha256).digest())
    return hmac.compare_digest(digest, header_hmac.strip().encode())

import os
import hmac
import hashlib
import urllib.parse
import httpx


def _api_key() -> str:
    return os.getenv("SHOPIFY_API_KEY", "")


def _api_secret() -> str:
    return os.getenv("SHOPIFY_API_SECRET", "")


def public_app_url() -> str:
    url = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://shopify-jarvis.onrender.com"
    return url.rstrip("/")


# Kept for backwards compatibility with older imports.
SHOPIFY_API_KEY = _api_key()
SHOPIFY_API_SECRET = _api_secret()
APP_URL = public_app_url()

SCOPES = (
    "read_orders,read_products,read_customers,"
    "read_checkouts,read_analytics,read_inventory"
)


def verify_hmac(params: dict) -> bool:
    """Validate Shopify's HMAC signature on the OAuth callback query string."""
    secret = _api_secret()
    received_hmac = str(params.pop("hmac", "") or "")
    if not secret or not received_hmac:
        return False
    sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hmac.new(secret.encode("utf-8"), sorted_params.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, received_hmac)


def build_install_url(shop: str, nonce: str) -> str:
    """Build the Shopify OAuth authorization URL."""
    query = urllib.parse.urlencode({
        "client_id": _api_key(),
        "scope": SCOPES,
        "redirect_uri": f"{public_app_url()}/auth/callback",
        "state": nonce,
    })
    return f"https://{shop}/admin/oauth/authorize?{query}"


async def exchange_code_for_token(shop: str, code: str) -> str:
    """Exchange OAuth code for a permanent access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": _api_key(),
                "client_secret": _api_secret(),
                "code": code,
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def fetch_client_credentials_token(shop: str) -> tuple:
    """
    Client credentials grant (Dev Dashboard apps installed on a store of the same organization).
    Returns (access_token, expires_in_seconds). Tokens last ~24h, so callers must refresh.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": _api_key(),
                "client_secret": _api_secret(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        if r.status_code != 200:
            detail = ""
            try:
                body = r.json()
                detail = body.get("error_description") or body.get("error") or ""
            except Exception:
                detail = r.text[:200]
            raise RuntimeError(f"Shopify token request failed ({r.status_code}): {detail}")
        body = r.json()
        token = body.get("access_token")
        if not token:
            raise RuntimeError("Shopify token response had no access_token")
        return token, int(body.get("expires_in") or 86399)

import os
import hmac
import hashlib
import urllib.parse
import uuid
import httpx


SHOPIFY_API_KEY    = os.getenv("SHOPIFY_API_KEY", "")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET", "")
APP_URL            = os.getenv("APP_URL") or os.getenv("APP URL") or "https://shopify-jarvis-production.up.railway.app"
SCOPES = (
    "read_orders,read_products,read_customers,"
    "read_checkouts,read_analytics,read_inventory"
)


def verify_hmac(params: dict) -> bool:
    """Validate Shopify HMAC signature on OAuth callback."""
    received_hmac = params.pop("hmac", "")
    sorted_params  = "&".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    digest = hmac.new(
        SHOPIFY_API_SECRET.encode("utf-8"),
        sorted_params.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, received_hmac)


def build_install_url(shop: str, nonce: str) -> str:
    """Build the Shopify OAuth authorization URL."""
    return (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_API_KEY}"
        f"&scope={SCOPES}"
        f"&redirect_uri={APP_URL}/auth/callback"
        f"&state={nonce}"
    )


async def exchange_code_for_token(shop: str, code: str) -> str:
    """Exchange OAuth code for a permanent access token."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id":     SHOPIFY_API_KEY,
                "client_secret": SHOPIFY_API_SECRET,
                "code":          code,
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]

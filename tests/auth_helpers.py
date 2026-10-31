"""
Shared auth fixtures for tests that call the FastAPI app.

Protected routes need either the admin key header or a Shopify session token,
and webhooks need a valid X-Shopify-Hmac-Sha256 signature. Import this module
BEFORE importing `main` so the env vars are in place.
"""
import base64
import hashlib
import hmac
import os

TEST_ADMIN_KEY = os.environ.setdefault("JARVIS_ADMIN_KEY", "test-admin-key-0123456789")
TEST_API_KEY = os.environ.setdefault("SHOPIFY_API_KEY", "test_api_key_123")
TEST_API_SECRET = os.environ.setdefault("SHOPIFY_API_SECRET", "test_api_secret_456")
os.environ.setdefault("JARVIS_DISABLE_DAEMON", "1")

AUTH_HEADERS = {"X-Jarvis-Key": TEST_ADMIN_KEY}


def admin_key() -> str:
    return os.environ.get("JARVIS_ADMIN_KEY", TEST_ADMIN_KEY)


def auth_headers() -> dict:
    return {"X-Jarvis-Key": admin_key()}


def webhook_headers(body: bytes, shop: str = "maisongrozavu.myshopify.com", secret: str = None) -> dict:
    secret = secret if secret is not None else os.environ.get("SHOPIFY_API_SECRET", TEST_API_SECRET)
    sig = base64.b64encode(hmac.new(secret.encode(), body or b"", hashlib.sha256).digest()).decode()
    return {"X-Shopify-Hmac-Sha256": sig, "X-Shopify-Shop-Domain": shop, "Content-Type": "application/json"}


def authed_client(app):
    from starlette.testclient import TestClient
    return TestClient(app, headers=auth_headers())


def block_network():
    """Start a patch that makes every outgoing httpx.AsyncClient request fail like an offline machine.
    Tests that need a specific response still patch get/post themselves. Returns the patcher (call .stop())."""
    from unittest.mock import patch
    import httpx

    async def _offline(self, request, *args, **kwargs):
        raise httpx.ConnectError("network disabled in tests", request=request)

    patcher = patch("httpx.AsyncClient.send", new=_offline)
    patcher.start()
    return patcher

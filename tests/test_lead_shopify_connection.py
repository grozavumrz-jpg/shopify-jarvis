"""Shopify connection through the client credentials grant (Dev Dashboard app, ~24h tokens)."""
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from tests.auth_helpers import AUTH_HEADERS  # noqa: E402,F401
except ImportError:
    from auth_helpers import AUTH_HEADERS  # noqa: E402,F401

import database as db  # noqa: E402
import main  # noqa: E402
import shopify_auth  # noqa: E402

CC_ENV = {"SHOPIFY_AUTH_MODE": "auto", "SHOPIFY_API_KEY": "client_id_x", "SHOPIFY_API_SECRET": "client_secret_y",
          "SHOPIFY_ACCESS_TOKEN": "", "SHOP_DOMAIN": "cc-test-store.myshopify.com"}


class TestClientCredentialsConnection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        db.init_db()
        main.SHOPIFY_CONNECTION.update(mode="none", expires_at=0.0, error=None, retry_after=0.0)

    async def test_token_is_fetched_stored_and_reused(self):
        fetch = AsyncMock(return_value=("shpat_cc0123456789abcdef0123456789ab", 86399))
        with patch.dict(os.environ, CC_ENV), patch.object(main, "fetch_client_credentials_token", fetch):
            await main.ensure_shop_connection()
            await main.ensure_shop_connection()  # still valid -> no second request
        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(main.SHOPIFY_CONNECTION["mode"], "client_credentials")
        self.assertEqual(db.get_shop("cc-test-store.myshopify.com")["access_token"],
                         "shpat_cc0123456789abcdef0123456789ab")

    async def test_token_is_refreshed_before_it_expires(self):
        fetch = AsyncMock(side_effect=[("shpat_first0123456789abcdef01234567", 86399),
                                       ("shpat_second123456789abcdef01234567", 86399)])
        with patch.dict(os.environ, CC_ENV), patch.object(main, "fetch_client_credentials_token", fetch):
            await main.ensure_shop_connection()
            main.SHOPIFY_CONNECTION["expires_at"] = time.time() + 600  # 10 minutes left
            await main.ensure_shop_connection()
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(db.get_shop("cc-test-store.myshopify.com")["access_token"],
                         "shpat_second123456789abcdef01234567")

    async def test_failure_is_reported_and_not_hammered(self):
        fetch = AsyncMock(side_effect=RuntimeError("shop_not_permitted"))
        with patch.dict(os.environ, CC_ENV), patch.object(main, "fetch_client_credentials_token", fetch):
            await main.ensure_shop_connection()
            await main.ensure_shop_connection()
        self.assertEqual(fetch.await_count, 1)
        self.assertIn("shop_not_permitted", main.SHOPIFY_CONNECTION["error"])

    async def test_store_outside_org_backs_off_for_hours_with_a_hint(self):
        fetch = AsyncMock(side_effect=RuntimeError(
            "Shopify token request failed (400): Client credentials cannot be performed on this shop."))
        with patch.dict(os.environ, CC_ENV), patch.object(main, "fetch_client_credentials_token", fetch):
            await main.ensure_shop_connection()
        self.assertGreater(main.SHOPIFY_CONNECTION["retry_after"] - time.time(), 5 * 3600)
        self.assertIn("Shopify Admin", main.SHOPIFY_CONNECTION["error"])

    async def test_health_reports_oauth_token_and_hides_stale_cc_error(self):
        from starlette.testclient import TestClient
        main.SHOPIFY_CONNECTION.update(mode="none", error="shop_not_permitted")
        with patch.dict(os.environ, dict(CC_ENV, SHOP_DOMAIN="oauth-test-store.myshopify.com")):
            db.upsert_shop("oauth-test-store.myshopify.com", "shpua_oauth0123456789abcdef012345", "Test")
            data = TestClient(main.app).get("/health").json()
        self.assertEqual(data["shopify_connection"], "oauth")
        self.assertIsNone(data["shopify_connection_error"])
        self.assertEqual(data["shopify_shop"], "oauth-test-store.myshopify.com")

    async def test_static_token_wins_over_client_credentials(self):
        fetch = AsyncMock()
        env = dict(CC_ENV, SHOPIFY_ACCESS_TOKEN="shpat_static0123456789abcdef0123456")
        with patch.dict(os.environ, env), patch.object(main, "fetch_client_credentials_token", fetch):
            await main.ensure_shop_connection()
        fetch.assert_not_awaited()
        self.assertEqual(main.SHOPIFY_CONNECTION["mode"], "env_token")

    async def test_oauth_mode_disables_client_credentials(self):
        fetch = AsyncMock()
        with patch.dict(os.environ, dict(CC_ENV, SHOPIFY_AUTH_MODE="oauth")), \
                patch.object(main, "fetch_client_credentials_token", fetch):
            await main.ensure_shop_connection()
        fetch.assert_not_awaited()


class TestTokenRequest(unittest.IsolatedAsyncioTestCase):
    async def test_request_shape_and_error_message(self):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"access_token": "tok", "scope": "read_orders", "expires_in": 86399}
        with patch.dict(os.environ, CC_ENV), patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok) as post:
            token, ttl = await shopify_auth.fetch_client_credentials_token("cc-test-store.myshopify.com")
        self.assertEqual((token, ttl), ("tok", 86399))
        url = post.call_args.args[0]
        self.assertEqual(url, "https://cc-test-store.myshopify.com/admin/oauth/access_token")
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "client_credentials")

        bad = MagicMock(status_code=400)
        bad.json.return_value = {"error": "shop_not_permitted",
                                 "error_description": "Client credentials cannot be performed on this shop."}
        with patch.dict(os.environ, CC_ENV), patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=bad):
            with self.assertRaises(RuntimeError) as ctx:
                await shopify_auth.fetch_client_credentials_token("cc-test-store.myshopify.com")
        self.assertIn("cannot be performed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

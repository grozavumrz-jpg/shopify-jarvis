"""
Unit tests for backend/shopify_api.py
Validates:
1. Enriched line items with images (direct and fallback lookup)
2. Negative and positive caching of product images
3. Clean abandoned_checkout_url preservation (no premature MG10)
4. append_discount_to_url utility behavior
5. Parameter passing and defaults for get_abandoned_checkouts_detailed
"""
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
from shopify_api import ShopifyClient, detect_customer_language_and_country


class TestShopifyClientLineItems(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.client = ShopifyClient("test-shop.myshopify.com", "shpat_test_token_123")

    async def test_direct_image_url_preserved_without_api_call(self):
        """Line item with direct image_url does not trigger product API lookup."""
        mock_checkout = {
            "id": 1001,
            "abandoned_checkout_url": "https://test-shop.myshopify.com/checkouts/ac/token1",
            "line_items": [
                {
                    "title": "Silk Kimono",
                    "variant_title": "Gold / L",
                    "quantity": 1,
                    "price": "220.00",
                    "image_url": "https://cdn.shopify.com/files/kimono.jpg",
                    "product_id": 999,
                    "variant_id": 888,
                    "sku": "KIM-GLD-L",
                }
            ],
        }

        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})

        res = await self.client.get_abandoned_checkouts_detailed()

        self.assertEqual(len(res), 1)
        checkout = res[0]
        self.assertEqual(len(checkout["line_items"]), 1)
        li = checkout["line_items"][0]
        self.assertEqual(li["title"], "Silk Kimono")
        self.assertEqual(li["variant_title"], "Gold / L")
        self.assertEqual(li["quantity"], 1)
        self.assertEqual(li["price"], "220.00")
        self.assertEqual(li["image_url"], "https://cdn.shopify.com/files/kimono.jpg")
        self.assertEqual(checkout["image_url"], "https://cdn.shopify.com/files/kimono.jpg")
        # Only checkouts.json should have been requested, no product API call
        self.assertEqual(self.client._get.call_count, 1)

    async def test_fallback_product_image_lookup(self):
        """Line item without image_url triggers get_product_image_url fallback."""
        mock_checkout = {
            "id": 1002,
            "abandoned_checkout_url": "https://test-shop.myshopify.com/checkouts/ac/token2",
            "line_items": [
                {
                    "title": "Cashmere Knit",
                    "variant_title": "Noir / M",
                    "quantity": 2,
                    "price": 145.0,
                    "product_id": 555,
                    "variant_id": 666,
                }
            ],
        }

        async def fake_get(path, params=None):
            if path == "/checkouts.json":
                return {"checkouts": [mock_checkout]}
            if "/products/555.json" in path:
                return {
                    "product": {
                        "id": 555,
                        "image": {"src": "https://cdn.shopify.com/files/knit_noir.jpg"},
                        "images": [{"id": 1, "src": "https://cdn.shopify.com/files/knit_noir.jpg"}],
                    }
                }
            return {}

        self.client._get = AsyncMock(side_effect=fake_get)

        res = await self.client.get_abandoned_checkouts_detailed()

        self.assertEqual(len(res), 1)
        li = res[0]["line_items"][0]
        self.assertEqual(li["price"], "145.00")
        self.assertEqual(li["image_url"], "https://cdn.shopify.com/files/knit_noir.jpg")
        self.assertEqual(res[0]["image_url"], "https://cdn.shopify.com/files/knit_noir.jpg")

    async def test_caching_across_multiple_items_with_same_product(self):
        """Repeated product IDs in checkouts query Product API only once."""
        mock_checkout = {
            "id": 1003,
            "abandoned_checkout_url": "https://test-shop.myshopify.com/checkouts/ac/token3",
            "line_items": [
                {"title": "Item Variant 1", "product_id": 777, "variant_id": 1, "price": "50.00"},
                {"title": "Item Variant 2", "product_id": 777, "variant_id": 2, "price": "50.00"},
            ],
        }

        calls = []

        async def fake_get(path, params=None):
            calls.append(path)
            if path == "/checkouts.json":
                return {"checkouts": [mock_checkout]}
            if "/products/777.json" in path:
                return {
                    "product": {
                        "id": 777,
                        "image": {"src": "https://cdn.shopify.com/files/item777.jpg"},
                    }
                }
            return {}

        self.client._get = AsyncMock(side_effect=fake_get)

        res = await self.client.get_abandoned_checkouts_detailed()

        self.assertEqual(len(res[0]["line_items"]), 2)
        # Check that /products/777.json was requested only once
        product_calls = [p for p in calls if "/products/777.json" in p]
        self.assertEqual(len(product_calls), 1)
        self.assertEqual(res[0]["line_items"][0]["image_url"], "https://cdn.shopify.com/files/item777.jpg")
        self.assertEqual(res[0]["line_items"][1]["image_url"], "https://cdn.shopify.com/files/item777.jpg")

    async def test_negative_caching_on_deleted_product(self):
        """Failed product lookup caches None to prevent repeated API hammering."""
        self.client._get = AsyncMock(side_effect=Exception("404 Not Found"))

        url1 = await self.client.get_product_image_url(404404)
        url2 = await self.client.get_product_image_url(404404)

        self.assertIsNone(url1)
        self.assertIsNone(url2)
        # Only 1 attempt made due to negative cache
        self.assertEqual(self.client._get.call_count, 1)


class TestShopifyClientCheckoutUrlPreservation(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.client = ShopifyClient("test-shop.myshopify.com", "shpat_test_token_123")

    async def test_raw_checkout_url_not_altered_with_mg10(self):
        """checkout_url must preserve raw Shopify URL without injecting discount=MG10."""
        raw_url = "https://luxury.myshopify.com/12345/checkouts/ac/token_xyz"
        mock_checkout = {
            "id": 2001,
            "abandoned_checkout_url": raw_url,
            "line_items": [],
        }

        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})

        res = await self.client.get_abandoned_checkouts_detailed()

        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["checkout_url"], raw_url)
        self.assertEqual(res[0]["abandoned_checkout_url"], raw_url)
        self.assertNotIn("discount=", res[0]["checkout_url"])

    async def test_checkout_url_with_existing_query_params_preserved(self):
        raw_url = "https://luxury.myshopify.com/12345/checkouts/ac/token_xyz?locale=it&step=contact_information"
        mock_checkout = {
            "id": 2002,
            "abandoned_checkout_url": raw_url,
            "line_items": [],
        }

        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})

        res = await self.client.get_abandoned_checkouts_detailed()

        self.assertEqual(res[0]["checkout_url"], raw_url)


class TestAppendDiscountToUrl(unittest.TestCase):

    def test_clean_url_gets_discount_param(self):
        url = "https://shop.com/checkouts/ac/123"
        res = ShopifyClient.append_discount_to_url(url, "MG10")
        self.assertEqual(res, "https://shop.com/checkouts/ac/123?discount=MG10")

    def test_url_with_query_param_gets_ampersand(self):
        url = "https://shop.com/checkouts/ac/123?locale=ro"
        res = ShopifyClient.append_discount_to_url(url, "MG10")
        self.assertEqual(res, "https://shop.com/checkouts/ac/123?locale=ro&discount=MG10")

    def test_avoid_duplicate_discount(self):
        url = "https://shop.com/checkouts/ac/123?discount=MG10"
        res = ShopifyClient.append_discount_to_url(url, "MG10")
        self.assertEqual(res, url)

    def test_none_or_empty_discount_returns_unmodified_url(self):
        url = "https://shop.com/checkouts/ac/123"
        self.assertEqual(ShopifyClient.append_discount_to_url(url, None), url)
        self.assertEqual(ShopifyClient.append_discount_to_url(url, ""), url)

    def test_empty_url_returns_empty_string(self):
        self.assertEqual(ShopifyClient.append_discount_to_url("", "MG10"), "")
        self.assertEqual(ShopifyClient.append_discount_to_url(None, "MG10"), "")


class TestShopifyClientDefensiveIngestion(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = ShopifyClient("test-shop.myshopify.com", "shpat_test_token_123")

    async def test_checkouts_none_returns_empty_list(self):
        """Verify get_abandoned_checkouts_detailed handles {'checkouts': None} gracefully."""
        self.client._get = AsyncMock(return_value={"checkouts": None})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(res, [])

    async def test_get_abandoned_checkouts_simple_none(self):
        """Verify get_abandoned_checkouts handles {'checkouts': None} gracefully."""
        self.client._get = AsyncMock(return_value={"checkouts": None})
        res = await self.client.get_abandoned_checkouts()
        self.assertEqual(res, [])

    async def test_total_price_non_numeric_defaults_to_zero(self):
        """Verify non-numeric total_price strings ('free', 'N/A', etc.) default to 0.0."""
        mock_checkout = {
            "id": 1001,
            "abandoned_checkout_url": "https://test-shop.myshopify.com/checkouts/ac/1001",
            "total_price": "free",
            "line_items": []
        }
        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["total_price"], 0.0)

    async def test_total_price_none_defaults_to_zero(self):
        """Verify None total_price defaults to 0.0."""
        mock_checkout = {
            "id": 1002,
            "abandoned_checkout_url": "https://test-shop.myshopify.com/checkouts/ac/1002",
            "total_price": None,
            "line_items": []
        }
        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["total_price"], 0.0)

    async def test_phone_integer_type_normalized_to_string(self):
        """Verify integer phone numbers are safely normalized to string without crashing .replace() or iteration."""
        mock_checkout = {
            "id": 1003,
            "abandoned_checkout_url": "https://test-shop.myshopify.com/checkouts/ac/1003",
            "phone": 40722123456,
            "line_items": []
        }
        self.client._get = AsyncMock(return_value={"checkouts": [mock_checkout]})
        res = await self.client.get_abandoned_checkouts_detailed()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["phone"], "40722123456")
        self.assertEqual(res[0]["clean_phone"], "40722123456")
        self.assertTrue(res[0]["has_phone"])

    def test_detect_customer_language_with_integer_phone(self):
        """Verify detect_customer_language_and_country does not crash when passed an integer phone."""
        res = detect_customer_language_and_country("Ioan Popescu", "", 40722123456, "", "")
        self.assertEqual(res["lang"], "ro")


if __name__ == "__main__":
    unittest.main()

